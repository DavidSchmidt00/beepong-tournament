import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE,
    create_session_value,
    hash_password,
    require_auth,
    verify_password,
)
from app.database import get_db, init_db
from app.models import Match, MatchRound, MatchStatus, Team, Tournament, TournamentStatus
from app import tournament as tour_logic


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")


# ── Root redirect ─────────────────────────────────────────────────────────────

@app.get("/")
def root(db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament or tournament.status == TournamentStatus.setup:
        return RedirectResponse(url="/setup")
    return RedirectResponse(url="/admin")


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def post_login(request: Request, password: str = Form(...), db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if tournament and verify_password(password, tournament.admin_password_hash):
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie(SESSION_COOKIE, create_session_value(password), httponly=True, samesite="lax")
        return response
    return templates.TemplateResponse(request, "login.html", {"error": "Falsches Passwort"}, status_code=401)


@app.post("/logout")
def post_logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ── Setup routes ──────────────────────────────────────────────────────────────

@app.get("/setup", response_class=HTMLResponse)
def get_setup(request: Request, db: Session = Depends(get_db)):
    existing = db.query(Tournament).first()
    if existing and existing.status != TournamentStatus.setup:
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse(request, "setup.html", {"num_players_options": [8, 10, 12, 14, 16]})


@app.post("/setup")
async def post_setup(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    title = form.get("title", "Beer Pong Turnier")
    num_players = int(form.get("num_players", 12))
    admin_password = form.get("admin_password", "")
    num_teams = num_players // 2

    teams_input = [
        {
            "name": form.get(f"team_name_{i}", f"Team {i}"),
            "player1": form.get(f"player1_{i}", ""),
            "player2": form.get(f"player2_{i}", ""),
        }
        for i in range(1, num_teams + 1)
    ]
    random.shuffle(teams_input)

    tournament = Tournament(
        title=title,
        status=TournamentStatus.group_stage,
        admin_password_hash=hash_password(admin_password),
        num_players=num_players,
    )
    db.add(tournament)
    db.flush()

    team_objs = []
    for td in teams_input:
        t = Team(
            tournament_id=tournament.id,
            name=td["name"],
            player1=td["player1"],
            player2=td["player2"],
            group="A",
        )
        db.add(t)
        team_objs.append(t)
    db.flush()

    team_dicts = [{"id": t.id, "name": t.name, "group": None} for t in team_objs]
    group_a_dicts, group_b_dicts = tour_logic.split_into_groups(team_dicts)

    group_a_ids = {d["id"] for d in group_a_dicts}
    for t in team_objs:
        t.group = "A" if t.id in group_a_ids else "B"

    match_specs = tour_logic.generate_round_robin(group_a_dicts, "A") + tour_logic.generate_round_robin(group_b_dicts, "B")
    for ms in match_specs:
        db.add(Match(tournament_id=tournament.id, **ms))

    db.commit()

    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(SESSION_COOKIE, create_session_value(admin_password), httponly=True, samesite="lax")
    return response


# ── Bracket context helper ────────────────────────────────────────────────────

def _build_bracket_context(tournament: Tournament, db: Session) -> dict:
    teams = tournament.teams
    matches = tournament.matches

    group_a_teams = [t for t in teams if t.group == "A"]
    group_b_teams = [t for t in teams if t.group == "B"]
    group_a_matches = [m for m in matches if m.group == "A" and m.round == MatchRound.group]
    group_b_matches = [m for m in matches if m.group == "B" and m.round == MatchRound.group]

    def to_dict(m: Match) -> dict:
        return {
            "id": m.id,
            "team_a_id": m.team_a_id,
            "team_b_id": m.team_b_id,
            "group": m.group,
            "round": m.round,
            "status": m.status,
            "winner_id": m.winner_id,
            "cups_a": m.cups_a,
            "cups_b": m.cups_b,
        }

    team_dicts_a = [{"id": t.id, "name": t.name, "group": t.group} for t in group_a_teams]
    team_dicts_b = [{"id": t.id, "name": t.name, "group": t.group} for t in group_b_teams]

    standings_a = tour_logic.calculate_standings(team_dicts_a, [to_dict(m) for m in group_a_matches])
    standings_b = tour_logic.calculate_standings(team_dicts_b, [to_dict(m) for m in group_b_matches])

    team_map = {t.id: t for t in teams}
    for s in standings_a + standings_b:
        s["name"] = team_map[s["team_id"]].name
        s["player1"] = team_map[s["team_id"]].player1
        s["player2"] = team_map[s["team_id"]].player2

    pending_matches = [m for m in matches if m.status == MatchStatus.pending]
    completed_count = sum(1 for m in matches if m.status == MatchStatus.completed)
    ko_matches = [m for m in matches if m.round != MatchRound.group]

    return {
        "tournament": tournament,
        "standings_a": standings_a,
        "standings_b": standings_b,
        "pending_matches": pending_matches,
        "completed_count": completed_count,
        "total_count": len(matches),
        "ko_matches": ko_matches,
        "all_matches": matches,
        "team_map": team_map,
    }


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return RedirectResponse(url="/setup")
    ctx = _build_bracket_context(tournament, db)
    return templates.TemplateResponse(request, "admin.html", ctx)


@app.post("/matches/{match_id}/result")
def post_result(
    match_id: int,
    winner_id: int = Form(...),
    cups_a: int = Form(...),
    cups_b: int = Form(...),
    db: Session = Depends(get_db),
    _=Depends(require_auth),
):
    match = db.query(Match).filter_by(id=match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    match.winner_id = winner_id
    match.cups_a = cups_a
    match.cups_b = cups_b
    match.status = MatchStatus.completed
    match.played_at = datetime.now(timezone.utc)
    db.flush()

    tournament = db.query(Tournament).filter_by(id=match.tournament_id).first()
    group_matches = [m for m in tournament.matches if m.round == MatchRound.group]

    if all(m.status == MatchStatus.completed for m in group_matches):
        ko_existing = [m for m in tournament.matches if m.round == MatchRound.semifinal]
        if not ko_existing:
            _generate_ko_matches(tournament, db)
            tournament.status = TournamentStatus.knockout

    db.expire(tournament, ["matches"])
    semis = [m for m in tournament.matches if m.round == MatchRound.semifinal]
    if semis and all(m.status == MatchStatus.completed for m in semis):
        final = next((m for m in tournament.matches if m.round == MatchRound.final), None)
        third = next((m for m in tournament.matches if m.round == MatchRound.third_place), None)
        if final and final.team_a_id is None:
            winners = [m.winner_id for m in semis]
            losers = [
                m.team_a_id if m.winner_id == m.team_b_id else m.team_b_id
                for m in semis
            ]
            final.team_a_id, final.team_b_id = winners[0], winners[1]
            if third:
                third.team_a_id, third.team_b_id = losers[0], losers[1]

    final_match = next((m for m in tournament.matches if m.round == MatchRound.final), None)
    if final_match and final_match.status == MatchStatus.completed:
        tournament.status = TournamentStatus.finished

    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


def _generate_ko_matches(tournament: Tournament, db: Session) -> None:
    teams = tournament.teams
    group_a_teams = [{"id": t.id, "name": t.name, "group": t.group} for t in teams if t.group == "A"]
    group_b_teams = [{"id": t.id, "name": t.name, "group": t.group} for t in teams if t.group == "B"]
    group_a_matches = [m for m in tournament.matches if m.group == "A" and m.round == MatchRound.group]
    group_b_matches = [m for m in tournament.matches if m.group == "B" and m.round == MatchRound.group]

    def to_dict(m: Match) -> dict:
        return {
            "id": m.id, "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
            "group": m.group, "round": m.round, "status": m.status,
            "winner_id": m.winner_id, "cups_a": m.cups_a, "cups_b": m.cups_b,
        }

    standings_a = tour_logic.calculate_standings(group_a_teams, [to_dict(m) for m in group_a_matches])
    standings_b = tour_logic.calculate_standings(group_b_teams, [to_dict(m) for m in group_b_matches])

    for ks in tour_logic.get_ko_pairings(standings_a, standings_b):
        db.add(Match(
            tournament_id=tournament.id,
            team_a_id=ks["team_a_id"],
            team_b_id=ks["team_b_id"],
            round=ks["round"],
            group=ks["group"],
            status=ks["status"],
        ))


# ── TV + partial routes ───────────────────────────────────────────────────────

@app.get("/tv", response_class=HTMLResponse)
def get_tv(request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return RedirectResponse(url="/setup")
    ctx = _build_bracket_context(tournament, db)
    return templates.TemplateResponse(request, "tv.html", ctx)


@app.get("/partials/bracket", response_class=HTMLResponse)
def get_bracket_partial(request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return HTMLResponse("<p>Kein Turnier aktiv</p>")
    ctx = _build_bracket_context(tournament, db)
    return templates.TemplateResponse(request, "partials/bracket.html", ctx)
