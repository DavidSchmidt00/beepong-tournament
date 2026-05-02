import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
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
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# ── Root / Landing Page ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament or tournament.status == TournamentStatus.setup:
        admin_url = "/setup"
    else:
        admin_url = "/admin"
    return templates.TemplateResponse(request, "landing.html", {
        "tournament": tournament,
        "admin_url": admin_url,
    })


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


@app.post("/reset")
def post_reset(db: Session = Depends(get_db), _=Depends(require_auth)):
    db.query(Match).delete()
    db.query(Team).delete()
    db.query(Tournament).delete()
    db.commit()
    return RedirectResponse(url="/setup", status_code=302)


# ── Setup routes ──────────────────────────────────────────────────────────────

@app.get("/setup", response_class=HTMLResponse)
def get_setup(request: Request, db: Session = Depends(get_db)):
    existing = db.query(Tournament).first()
    if existing and existing.status != TournamentStatus.setup:
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse(request, "setup.html", {})


@app.post("/setup")
async def post_setup(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    title = form.get("title", "Beer Pong Turnier")
    admin_password = form.get("admin_password", "")
    num_teams_raw = int(form.get("num_teams", 0))

    teams_input = []
    for i in range(1, num_teams_raw + 1):
        name = (form.get(f"team_name_{i}") or "").strip()
        if not name:
            continue
        teams_input.append({
            "name": name,
            "emoji": form.get(f"emoji_{i}") or "🍺",
            "player1": (form.get(f"player1_{i}") or "").strip() or None,
            "player2": (form.get(f"player2_{i}") or "").strip() or None,
        })
    num_teams = len(teams_input)
    initial_status = TournamentStatus.knockout if num_teams <= 4 else TournamentStatus.group_stage
    random.shuffle(teams_input)

    tournament = Tournament(
        title=title,
        status=initial_status,
        admin_password_hash=hash_password(admin_password),
        num_players=num_teams * 2,
    )
    db.add(tournament)
    db.flush()

    team_objs = []
    for td in teams_input:
        t = Team(
            tournament_id=tournament.id,
            name=td["name"],
            emoji=td["emoji"],
            player1=td["player1"],
            player2=td["player2"],
            group="A",
        )
        db.add(t)
        team_objs.append(t)
    db.flush()

    if num_teams <= 4:
        for t in team_objs:
            t.group = "A"
        team_dicts = [{"id": t.id, "name": t.name} for t in team_objs]
        match_specs = tour_logic.generate_direct_ko_bracket(team_dicts)
    elif num_teams <= 8:
        team_dicts = [{"id": t.id, "name": t.name, "group": None} for t in team_objs]
        group_a_dicts, group_b_dicts = tour_logic.split_into_groups(team_dicts)
        group_a_ids = {d["id"] for d in group_a_dicts}
        for t in team_objs:
            t.group = "A" if t.id in group_a_ids else "B"
        match_specs = tour_logic.generate_round_robin(group_a_dicts, "A") + tour_logic.generate_round_robin(group_b_dicts, "B")
    else:
        team_dicts = [{"id": t.id, "name": t.name, "group": None} for t in team_objs]
        ga, gb, gc, gd = tour_logic.split_into_four_groups(team_dicts)
        group_map = {d["id"]: g for g, grp in zip(["A", "B", "C", "D"], [ga, gb, gc, gd]) for d in grp}
        for t in team_objs:
            t.group = group_map[t.id]
        match_specs = (
            tour_logic.generate_round_robin(ga, "A") +
            tour_logic.generate_round_robin(gb, "B") +
            tour_logic.generate_round_robin(gc, "C") +
            tour_logic.generate_round_robin(gd, "D")
        )

    for ms in match_specs:
        db.add(Match(tournament_id=tournament.id, **ms))

    db.commit()

    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(SESSION_COOKIE, create_session_value(admin_password), httponly=True, samesite="lax")
    return response


# ── Bracket context helper ────────────────────────────────────────────────────

def _players_label(team) -> str:
    if not team:
        return ""
    parts = [p for p in (team.player1, team.player2) if p]
    return " & ".join(parts)


def _build_bracket_context(tournament: Tournament, db: Session) -> dict:
    teams = tournament.teams
    matches = sorted(tournament.matches, key=lambda m: m.id)
    group_labels = sorted({t.group for t in teams})

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

    def standings_for(label: str) -> list[dict]:
        grp_teams = [{"id": t.id, "name": t.name} for t in teams if t.group == label]
        grp_matches = [to_dict(m) for m in matches if m.group == label and m.round == MatchRound.group]
        return tour_logic.calculate_standings(grp_teams, grp_matches)

    standings_by_group = {label: standings_for(label) for label in group_labels}
    standings_a = standings_by_group.get("A", [])
    standings_b = standings_by_group.get("B", [])
    standings_c = standings_by_group.get("C", [])
    standings_d = standings_by_group.get("D", [])

    team_map = {t.id: t for t in teams}
    for s in standings_a + standings_b + standings_c + standings_d:
        s["name"] = team_map[s["team_id"]].name
        s["emoji"] = team_map[s["team_id"]].emoji
        s["player1"] = team_map[s["team_id"]].player1
        s["player2"] = team_map[s["team_id"]].player2
        s["is_on_fire"] = s["wins"] >= 3 or s["cup_diff"] >= 10

    all_pending = [m for m in matches if m.status == MatchStatus.pending]

    # Pin current match to position 0
    if tournament.current_match_id:
        current = next((m for m in all_pending if m.id == tournament.current_match_id), None)
        if current:
            all_pending = [current] + [m for m in all_pending if m.id != tournament.current_match_id]

    # Pin next match to position 1
    if tournament.next_match_id and len(all_pending) > 1:
        pinned = next((m for m in all_pending if m.id == tournament.next_match_id), None)
        if pinned and all_pending[0].id != tournament.next_match_id:
            rest = [m for m in all_pending[1:] if m.id != tournament.next_match_id]
            all_pending = [all_pending[0], pinned] + rest

    pending_matches = all_pending
    completed_count = sum(1 for m in matches if m.status == MatchStatus.completed)
    ko_matches = [m for m in matches if m.round != MatchRound.group]

    # Overall Ranking Logic
    overall_ranking = []
    final_m = next((m for m in ko_matches if m.round == MatchRound.final), None)
    third_m = next((m for m in ko_matches if m.round == MatchRound.third_place), None)
    
    # 1. Finalists
    if final_m and final_m.winner_id:
        w_id = final_m.winner_id
        r_id = final_m.team_b_id if w_id == final_m.team_a_id else final_m.team_a_id
        w = team_map.get(w_id)
        r = team_map.get(r_id)
        overall_ranking.append({
            "rank": 1, "team_id": w_id, "team_name": w.name if w else "Team",
            "team_emoji": w.emoji if w else "🏆", "team_players": _players_label(w),
            "status": "🏆 SIEGER"
        })
        overall_ranking.append({
            "rank": 2, "team_id": r_id, "team_name": r.name if r else "Team",
            "team_emoji": r.emoji if r else "🥈", "team_players": _players_label(r),
            "status": "🥈 2. PLATZ"
        })
    
    # 2. 3rd Place
    if third_m and third_m.winner_id:
        t3_id = third_m.winner_id
        t4_id = third_m.team_b_id if t3_id == third_m.team_a_id else third_m.team_a_id
        t3 = team_map.get(t3_id)
        t4 = team_map.get(t4_id)
        overall_ranking.append({
            "rank": 3, "team_id": t3_id, "team_name": t3.name if t3 else "Team",
            "team_emoji": t3.emoji if t3 else "🥉", "team_players": _players_label(t3),
            "status": "🥉 3. PLATZ"
        })
        overall_ranking.append({
            "rank": 4, "team_id": t4_id, "team_name": t4.name if t4 else "Team",
            "team_emoji": t4.emoji if t4 else "🍺", "team_players": _players_label(t4),
            "status": "4. PLATZ"
        })

    # 3. Add all other teams based on group stage performance
    ranked_ids = {r["team_id"] for r in overall_ranking}
    all_standings = standings_a + standings_b + standings_c + standings_d
    all_standings.sort(key=lambda x: (x["wins"], x["cup_diff"]), reverse=True)
    
    for s in all_standings:
        tid = s["team_id"]
        if tid not in ranked_ids:
            t = team_map.get(tid)
            overall_ranking.append({
                "rank": len(overall_ranking) + 1,
                "team_id": tid,
                "team_name": t.name if t else "Team",
                "team_emoji": t.emoji if t else "🍺",
                "team_players": _players_label(t),
                "status": f"{s['wins']}S / {s['losses']}N"
            })

    active_group_standings = [
        (label, standings_by_group[label])
        for label in group_labels
    ]

    return {
        "tournament": tournament,
        "current_match_id": tournament.current_match_id,
        "next_match_id": tournament.next_match_id,
        "standings_a": standings_a,
        "standings_b": standings_b,
        "standings_c": standings_c,
        "standings_d": standings_d,
        "group_labels": group_labels,
        "active_group_standings": active_group_standings,
        "pending_matches": pending_matches,
        "completed_count": completed_count,
        "total_count": len(matches),
        "ko_matches": ko_matches,
        "all_matches": matches,
        "team_map": team_map,
        "overall_ranking": overall_ranking,
    }


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return RedirectResponse(url="/setup")
    ctx = _build_bracket_context(tournament, db)
    ctx["request"] = request
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
    if tournament.current_match_id == match_id:
        tournament.current_match_id = None
    if tournament.next_match_id == match_id:
        tournament.next_match_id = None
    group_matches = [m for m in tournament.matches if m.round == MatchRound.group]

    if all(m.status == MatchStatus.completed for m in group_matches):
        ko_existing = [m for m in tournament.matches if m.round in (MatchRound.semifinal, MatchRound.quarterfinal)]
        if not ko_existing:
            _generate_ko_matches(tournament, db)
            tournament.status = TournamentStatus.knockout

    db.expire(tournament, ["matches"])

    # QF → SF: fill semifinal slots once all quarterfinals are done
    qf_matches = sorted([m for m in tournament.matches if m.round == MatchRound.quarterfinal], key=lambda m: m.id)
    if qf_matches and all(m.status == MatchStatus.completed for m in qf_matches):
        semis = sorted([m for m in tournament.matches if m.round == MatchRound.semifinal], key=lambda m: m.id)
        if semis and semis[0].team_a_id is None:
            # QF1/QF2 winners → SF1, QF3/QF4 winners → SF2
            semis[0].team_a_id = qf_matches[0].winner_id
            semis[0].team_b_id = qf_matches[1].winner_id
            semis[1].team_a_id = qf_matches[2].winner_id
            semis[1].team_b_id = qf_matches[3].winner_id

    semis = sorted([m for m in tournament.matches if m.round == MatchRound.semifinal], key=lambda m: m.id)
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


@app.post("/matches/reorder")
async def post_reorder_matches(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_auth),
):
    data = await request.json()
    order = data.get("order", [])
    tournament = db.query(Tournament).first()
    if not tournament:
        raise HTTPException(status_code=404)
    tournament.current_match_id = order[0] if len(order) > 0 else None
    tournament.next_match_id = order[1] if len(order) > 1 else None
    db.commit()
    return Response(status_code=204)


@app.post("/matches/{match_id}/start")
def post_start_match(
    match_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_auth),
):
    match = db.query(Match).filter_by(id=match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    match.started_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/matches/{match_id}/undo")
def post_undo_match(
    match_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_auth),
):
    match = db.query(Match).filter_by(id=match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    tournament = db.query(Tournament).filter_by(id=match.tournament_id).first()
    if tournament.status == TournamentStatus.finished:
        tournament.status = TournamentStatus.knockout

    # If it's a group match and knockout has started, we shouldn't really undo it
    # without resetting the knockout phase, but for simplicity we allow it or block it.
    if match.round == MatchRound.group and tournament.status in [TournamentStatus.knockout, TournamentStatus.finished]:
        raise HTTPException(status_code=400, detail="Cannot undo group match after KO phase started")

    match.winner_id = None
    match.cups_a = None
    match.cups_b = None
    match.status = MatchStatus.pending
    # We keep started_at so the timer doesn't fully reset, or we clear it:
    match.started_at = None
    match.played_at = None

    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/matches/{match_id}/set-current")
def post_set_current_match(
    match_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_auth),
):
    match = db.query(Match).filter_by(id=match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    tournament = db.query(Tournament).filter_by(id=match.tournament_id).first()
    tournament.current_match_id = match_id
    # If this match was queued as next, remove it from that slot
    if tournament.next_match_id == match_id:
        tournament.next_match_id = None
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/matches/{match_id}/set-next")
def post_set_next_match(
    match_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_auth),
):
    match = db.query(Match).filter_by(id=match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    tournament = db.query(Tournament).filter_by(id=match.tournament_id).first()
    tournament.next_match_id = match_id
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


def _generate_ko_matches(tournament: Tournament, db: Session) -> None:
    teams = tournament.teams
    group_labels = sorted({t.group for t in teams})
    four_groups = len(group_labels) == 4

    def to_dict(m: Match) -> dict:
        return {
            "id": m.id, "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
            "group": m.group, "round": m.round, "status": m.status,
            "winner_id": m.winner_id, "cups_a": m.cups_a, "cups_b": m.cups_b,
        }

    def standings_for(label: str):
        grp_teams = [{"id": t.id, "name": t.name} for t in teams if t.group == label]
        grp_matches = [to_dict(m) for m in tournament.matches if m.group == label and m.round == MatchRound.group]
        return tour_logic.calculate_standings(grp_teams, grp_matches)

    if four_groups:
        pairings = tour_logic.generate_quarterfinals(
            standings_for("A"), standings_for("B"),
            standings_for("C"), standings_for("D"),
        )
    else:
        pairings = tour_logic.get_ko_pairings(standings_for("A"), standings_for("B"))

    for ks in pairings:
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
        return templates.TemplateResponse(request, "tv.html", {"request": request, "tournament": None})
    ctx = _build_bracket_context(tournament, db)
    ctx["request"] = request
    return templates.TemplateResponse(request, "tv.html", ctx)


@app.get("/partials/bracket", response_class=HTMLResponse)
def get_bracket_partial(request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return templates.TemplateResponse(request, "partials/bracket.html", {"request": request, "tournament": None})
    ctx = _build_bracket_context(tournament, db)
    ctx["request"] = request
    return templates.TemplateResponse(request, "partials/bracket.html", ctx)
