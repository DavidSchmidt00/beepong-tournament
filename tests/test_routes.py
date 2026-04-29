import pytest
from app.models import Match, MatchRound, MatchStatus, Tournament, TournamentStatus, Team
from app.auth import hash_password, SESSION_COOKIE, create_session_value


def create_tournament(db, password="test123", status=TournamentStatus.group_stage):
    t = Tournament(
        title="Test Turnier",
        status=status,
        admin_password_hash=hash_password(password),
        num_players=12,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def auth_cookies(password="test123"):
    return {SESSION_COOKIE: create_session_value(password)}


def setup_full_tournament(db):
    t = Tournament(
        title="T", status=TournamentStatus.group_stage,
        admin_password_hash=hash_password("pw"), num_players=12,
    )
    db.add(t)
    db.flush()
    teams = []
    for i in range(1, 7):
        group = "A" if i <= 3 else "B"
        team = Team(tournament_id=t.id, name=f"Team{i}", player1=f"P{i}a", player2=f"P{i}b", group=group)
        db.add(team)
        teams.append(team)
    db.flush()
    pairs_a = [(teams[0], teams[1]), (teams[0], teams[2]), (teams[1], teams[2])]
    pairs_b = [(teams[3], teams[4]), (teams[3], teams[5]), (teams[4], teams[5])]
    for a, b in pairs_a + pairs_b:
        db.add(Match(tournament_id=t.id, team_a_id=a.id, team_b_id=b.id,
                     round=MatchRound.group, group=a.group, status=MatchStatus.pending))
    db.commit()
    db.refresh(t)
    return t


# Auth tests

def test_login_redirect_to_admin_on_correct_password(client, db):
    create_tournament(db, password="bier2024")
    response = client.post("/login", data={"password": "bier2024"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


def test_login_shows_error_on_wrong_password(client, db):
    create_tournament(db, password="bier2024")
    response = client.post("/login", data={"password": "wrong"})
    assert response.status_code == 401
    assert "Falsches Passwort" in response.text


def test_logout_clears_cookie(client, db):
    create_tournament(db)
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 302


# Setup tests

def test_setup_get_accessible_without_auth(client, db):
    response = client.get("/setup")
    assert response.status_code == 200
    assert "Turnier" in response.text


def test_setup_post_12_players_creates_6_group_matches(client, db):
    data = {"title": "T", "num_players": "12", "admin_password": "pw"}
    for i in range(1, 7):
        data[f"team_name_{i}"] = f"Team{i}"
        data[f"player1_{i}"] = f"P{i}a"
        data[f"player2_{i}"] = f"P{i}b"
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.status_code == 302
    tournament = db.query(Tournament).first()
    assert tournament is not None
    assert tournament.status == TournamentStatus.group_stage
    assert len(tournament.teams) == 6
    assert len(tournament.matches) == 6


def test_setup_redirects_to_admin(client, db):
    data = {"title": "T", "num_players": "4", "admin_password": "pw"}
    for i in range(1, 3):
        data[f"team_name_{i}"] = f"Team{i}"
        data[f"player1_{i}"] = f"P{i}a"
        data[f"player2_{i}"] = f"P{i}b"
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.headers["location"] == "/admin"


# Admin tests

def test_admin_requires_auth(client, db):
    setup_full_tournament(db)
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


def test_admin_accessible_with_auth(client, db):
    setup_full_tournament(db)
    response = client.get("/admin", cookies=auth_cookies("pw"))
    assert response.status_code == 200


def test_submit_result_updates_match(client, db):
    t = setup_full_tournament(db)
    match = db.query(Match).filter_by(tournament_id=t.id).first()
    winner_id = match.team_a_id
    response = client.post(
        f"/matches/{match.id}/result",
        data={"winner_id": str(winner_id), "cups_a": "3", "cups_b": "0"},
        cookies=auth_cookies("pw"),
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.refresh(match)
    assert match.status == MatchStatus.completed
    assert match.winner_id == winner_id
    assert match.cups_a == 3


def test_ko_matches_created_after_all_group_matches(client, db):
    t = setup_full_tournament(db)
    matches = db.query(Match).filter_by(tournament_id=t.id).all()
    for m in matches:
        client.post(
            f"/matches/{m.id}/result",
            data={"winner_id": str(m.team_a_id), "cups_a": "3", "cups_b": "0"},
            cookies=auth_cookies("pw"),
        )
    db.expire_all()
    ko_matches = db.query(Match).filter_by(tournament_id=t.id, round=MatchRound.semifinal).all()
    assert len(ko_matches) == 2


# TV tests

def test_tv_is_public(client, db):
    setup_full_tournament(db)
    response = client.get("/tv")
    assert response.status_code == 200


def test_partials_bracket_returns_html(client, db):
    setup_full_tournament(db)
    response = client.get("/partials/bracket")
    assert response.status_code == 200
    assert "Gruppe" in response.text


def test_tv_shows_next_match(client, db):
    setup_full_tournament(db)
    response = client.get("/tv")
    assert "Jetzt am Tisch" in response.text
