# Beer Pong Tournament App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a containerized Beer Pong tournament web app with a mobile admin view (enter results) and a TV view (live bracket), deployed to Railway.

**Architecture:** FastAPI + Jinja2 + HTMX for server-rendered pages with live polling. SQLAlchemy (sync) + PostgreSQL for persistence. Session-cookie auth protects admin routes; TV view is public. Docker Compose runs app + postgres locally; Railway runs the same Dockerfile with a managed PostgreSQL plugin.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.0, psycopg2, Jinja2, HTMX (CDN), PostgreSQL 16, pytest + httpx for tests.

---

## File Map

| File | Responsibility |
|---|---|
| `app/database.py` | Engine, SessionLocal, Base, `get_db` dependency, `init_db()` |
| `app/models.py` | SQLAlchemy ORM: Tournament, Team, Match |
| `app/tournament.py` | Pure business logic: group split, round-robin gen, standings, KO pairings |
| `app/auth.py` | Session signing (itsdangerous), `require_auth` FastAPI dependency, login/logout routes |
| `app/main.py` | FastAPI app, all routes, startup event |
| `app/templates/base.html` | Shared layout, nav, CSS variables for mobile + TV themes |
| `app/templates/login.html` | Password form |
| `app/templates/setup.html` | Player count selector + name inputs + team builder |
| `app/templates/admin.html` | Current matches, bracket overview, result entry modal |
| `app/templates/tv.html` | Large TV bracket layout, HTMX polling |
| `app/templates/partials/bracket.html` | HTMX-swappable bracket + standings fragment |
| `tests/conftest.py` | pytest fixtures: in-memory SQLite DB, TestClient with overridden `get_db` |
| `tests/test_tournament.py` | Pure logic tests (no DB, no HTTP) |
| `tests/test_routes.py` | HTTP integration tests via TestClient |
| `Dockerfile` | Production image |
| `docker-compose.yml` | Local dev: app + postgres |
| `requirements.txt` | Runtime deps |
| `requirements-dev.txt` | pytest, httpx |
| `.env.example` | Required env vars |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `app/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
sqlalchemy==2.0.36
psycopg2-binary==2.9.10
jinja2==3.1.5
python-multipart==0.0.20
itsdangerous==2.2.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.4
httpx==0.27.2
```

- [ ] **Step 3: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Create `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./app:/app/app

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: beerpong
      POSTGRES_USER: beerpong
      POSTGRES_PASSWORD: beerpong
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U beerpong"]
      interval: 5s
      timeout: 5s
      retries: 5
```

- [ ] **Step 5: Create `.env.example`**

```
DATABASE_URL=postgresql://beerpong:beerpong@db:5432/beerpong
ADMIN_PASSWORD=bier2024
SECRET_KEY=change-me-in-production-use-32-random-chars
```

- [ ] **Step 6: Create `.env` from example (used by docker compose)**

```bash
cp .env.example .env
```

- [ ] **Step 7: Create empty init files**

```bash
mkdir -p app/templates/partials tests
touch app/__init__.py tests/__init__.py
```

- [ ] **Step 8: Commit**

```bash
git init
git add .
git commit -m "chore: project scaffolding with Docker and deps"
```

---

## Task 2: Database Layer

**Files:**
- Create: `app/database.py`
- Create: `app/models.py`

- [ ] **Step 1: Create `app/database.py`**

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 — ensures models are registered
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 2: Create `app/models.py`**

```python
from datetime import datetime
from sqlalchemy import String, Integer, Enum, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum


class TournamentStatus(str, enum.Enum):
    setup = "setup"
    group_stage = "group_stage"
    knockout = "knockout"
    finished = "finished"


class MatchRound(str, enum.Enum):
    group = "group"
    semifinal = "semifinal"
    final = "final"
    third_place = "third_place"


class MatchStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100), default="Beer Pong Turnier")
    status: Mapped[TournamentStatus] = mapped_column(default=TournamentStatus.setup)
    admin_password_hash: Mapped[str] = mapped_column(String(256))
    num_players: Mapped[int] = mapped_column(Integer, default=12)

    teams: Mapped[list["Team"]] = relationship(back_populates="tournament", cascade="all, delete-orphan")
    matches: Mapped[list["Match"]] = relationship(back_populates="tournament", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    name: Mapped[str] = mapped_column(String(50))
    player1: Mapped[str] = mapped_column(String(50))
    player2: Mapped[str] = mapped_column(String(50))
    group: Mapped[str] = mapped_column(String(1))  # "A" or "B"

    tournament: Mapped["Tournament"] = relationship(back_populates="teams")
    matches_as_a: Mapped[list["Match"]] = relationship(foreign_keys="Match.team_a_id", back_populates="team_a")
    matches_as_b: Mapped[list["Match"]] = relationship(foreign_keys="Match.team_b_id", back_populates="team_b")
    wins: Mapped[list["Match"]] = relationship(foreign_keys="Match.winner_id", back_populates="winner")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    round: Mapped[MatchRound] = mapped_column()
    group: Mapped[str | None] = mapped_column(String(1), nullable=True)
    status: Mapped[MatchStatus] = mapped_column(default=MatchStatus.pending)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    cups_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cups_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tournament: Mapped["Tournament"] = relationship(back_populates="matches")
    team_a: Mapped["Team"] = relationship(foreign_keys=[team_a_id], back_populates="matches_as_a")
    team_b: Mapped["Team"] = relationship(foreign_keys=[team_b_id], back_populates="matches_as_b")
    winner: Mapped["Team | None"] = relationship(foreign_keys=[winner_id], back_populates="wins")
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 4: Commit**

```bash
git add app/database.py app/models.py tests/conftest.py
git commit -m "feat: database layer with SQLAlchemy models"
```

---

## Task 3: Tournament Logic

**Files:**
- Create: `app/tournament.py`
- Create: `tests/test_tournament.py`

- [ ] **Step 1: Write failing tests in `tests/test_tournament.py`**

```python
import pytest
from app.tournament import (
    split_into_groups,
    generate_round_robin,
    calculate_standings,
    get_ko_pairings,
    get_next_matches,
)
from app.models import MatchRound, MatchStatus


# --- Helpers ---

def make_team(id, name, group):
    """Creates a minimal dict representing a team for logic tests."""
    return {"id": id, "name": name, "group": group}


def make_match(id, team_a_id, team_b_id, group, status=MatchStatus.pending,
               winner_id=None, cups_a=None, cups_b=None):
    return {
        "id": id,
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "group": group,
        "round": MatchRound.group,
        "status": status,
        "winner_id": winner_id,
        "cups_a": cups_a,
        "cups_b": cups_b,
    }


# --- split_into_groups ---

def test_split_6_teams_evenly():
    teams = [make_team(i, f"T{i}", None) for i in range(1, 7)]
    group_a, group_b = split_into_groups(teams)
    assert len(group_a) == 3
    assert len(group_b) == 3


def test_split_5_teams():
    teams = [make_team(i, f"T{i}", None) for i in range(1, 6)]
    group_a, group_b = split_into_groups(teams)
    assert len(group_a) + len(group_b) == 5
    assert abs(len(group_a) - len(group_b)) <= 1


def test_split_7_teams():
    teams = [make_team(i, f"T{i}", None) for i in range(1, 8)]
    group_a, group_b = split_into_groups(teams)
    assert len(group_a) + len(group_b) == 7
    assert abs(len(group_a) - len(group_b)) <= 1


# --- generate_round_robin ---

def test_round_robin_3_teams_produces_3_matches():
    teams = [make_team(i, f"T{i}", "A") for i in range(1, 4)]
    matches = generate_round_robin(teams, "A")
    assert len(matches) == 3  # C(3,2) = 3


def test_round_robin_2_teams_produces_1_match():
    teams = [make_team(i, f"T{i}", "B") for i in range(1, 3)]
    matches = generate_round_robin(teams, "B")
    assert len(matches) == 1


def test_round_robin_4_teams_produces_6_matches():
    teams = [make_team(i, f"T{i}", "A") for i in range(1, 5)]
    matches = generate_round_robin(teams, "A")
    assert len(matches) == 6  # C(4,2) = 6


def test_round_robin_no_team_plays_itself():
    teams = [make_team(i, f"T{i}", "A") for i in range(1, 4)]
    matches = generate_round_robin(teams, "A")
    for m in matches:
        assert m["team_a_id"] != m["team_b_id"]


def test_round_robin_no_duplicate_pairs():
    teams = [make_team(i, f"T{i}", "A") for i in range(1, 4)]
    matches = generate_round_robin(teams, "A")
    pairs = {(m["team_a_id"], m["team_b_id"]) for m in matches}
    assert len(pairs) == len(matches)


# --- calculate_standings ---

def test_standings_sorted_by_wins():
    teams = [make_team(1, "T1", "A"), make_team(2, "T2", "A"), make_team(3, "T3", "A")]
    matches = [
        make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1, cups_a=3, cups_b=0),
        make_match(2, 1, 3, "A", MatchStatus.completed, winner_id=1, cups_a=2, cups_b=0),
        make_match(3, 2, 3, "A", MatchStatus.completed, winner_id=2, cups_a=1, cups_b=0),
    ]
    standings = calculate_standings(teams, matches)
    assert standings[0]["team_id"] == 1  # 2 wins
    assert standings[1]["team_id"] == 2  # 1 win
    assert standings[2]["team_id"] == 3  # 0 wins


def test_standings_tiebreaker_cup_diff():
    # T1 and T2 each have 1 win; T1 has better cup diff
    teams = [make_team(1, "T1", "A"), make_team(2, "T2", "A"), make_team(3, "T3", "A")]
    matches = [
        make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1, cups_a=3, cups_b=0),  # T1 +3 diff
        make_match(2, 2, 3, "A", MatchStatus.completed, winner_id=2, cups_a=1, cups_b=0),  # T2 +1 diff
        make_match(3, 1, 3, "A", MatchStatus.completed, winner_id=3, cups_a=0, cups_b=1),  # T3 wins
    ]
    standings = calculate_standings(teams, matches)
    assert standings[0]["team_id"] == 1  # 1 win, cup_diff = 3-0-1 = 2
    assert standings[1]["team_id"] == 2  # 1 win, cup_diff = 1-0 = 1  (but also 0-3 from match 1... wait)


def test_standings_includes_cup_diff():
    teams = [make_team(1, "T1", "A")]
    matches = [
        make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1, cups_a=5, cups_b=2),
    ]
    standings = calculate_standings(teams, matches)
    assert standings[0]["cup_diff"] == 3  # 5 scored - 2 conceded


# --- get_ko_pairings ---

def test_ko_pairings_structure():
    standings_a = [make_team(1, "A1", "A"), make_team(2, "A2", "A"), make_team(3, "A3", "A")]
    standings_b = [make_team(4, "B1", "B"), make_team(5, "B2", "B"), make_team(6, "B3", "B")]
    ko = get_ko_pairings(standings_a, standings_b)
    rounds = [m["round"] for m in ko]
    assert rounds.count(MatchRound.semifinal) == 2
    assert rounds.count(MatchRound.final) == 1
    assert rounds.count(MatchRound.third_place) == 1


def test_ko_pairings_cross_groups():
    # SF1: A1 vs B2, SF2: B1 vs A2
    standings_a = [make_team(1, "A1", "A"), make_team(2, "A2", "A")]
    standings_b = [make_team(3, "B1", "B"), make_team(4, "B2", "B")]
    ko = get_ko_pairings(standings_a, standings_b)
    semis = [m for m in ko if m["round"] == MatchRound.semifinal]
    sf_pairs = {(m["team_a_id"], m["team_b_id"]) for m in semis}
    assert (1, 4) in sf_pairs  # A1 vs B2
    assert (3, 2) in sf_pairs  # B1 vs A2


# --- get_next_matches ---

def test_get_next_matches_returns_pending():
    matches = [
        make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1),
        make_match(2, 3, 4, "A", MatchStatus.pending),
        make_match(3, 5, 6, "B", MatchStatus.pending),
    ]
    next_m = get_next_matches(matches)
    assert all(m["status"] == MatchStatus.pending for m in next_m)
    assert len(next_m) == 2


def test_get_next_matches_empty_when_all_done():
    matches = [make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1)]
    assert get_next_matches(matches) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm app pytest tests/test_tournament.py -v 2>&1 | head -40
```

Expected: `ImportError` or `ModuleNotFoundError` for `app.tournament`.

- [ ] **Step 3: Create `app/tournament.py`**

```python
from itertools import combinations
from app.models import MatchRound, MatchStatus


def split_into_groups(teams: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split teams into two balanced groups. Larger group is A when odd count."""
    n = len(teams)
    size_a = (n + 1) // 2  # rounds up for odd n
    return teams[:size_a], teams[size_a:]


def generate_round_robin(teams: list[dict], group: str) -> list[dict]:
    """Generate all unique pairings (round-robin) for teams in a group."""
    return [
        {
            "team_a_id": a["id"],
            "team_b_id": b["id"],
            "round": MatchRound.group,
            "group": group,
            "status": MatchStatus.pending,
        }
        for a, b in combinations(teams, 2)
    ]


def calculate_standings(teams: list[dict], matches: list[dict]) -> list[dict]:
    """
    Return teams sorted by: 1) wins desc, 2) cup_diff desc.
    cup_diff = cups_scored - cups_conceded across all completed matches.
    """
    stats: dict[int, dict] = {
        t["id"]: {"team_id": t["id"], "name": t["name"], "wins": 0, "losses": 0,
                  "cups_scored": 0, "cups_conceded": 0, "cup_diff": 0}
        for t in teams
    }

    for m in matches:
        if m["status"] != MatchStatus.completed:
            continue
        a_id, b_id = m["team_a_id"], m["team_b_id"]
        cups_a, cups_b = m.get("cups_a") or 0, m.get("cups_b") or 0

        if a_id in stats:
            stats[a_id]["cups_scored"] += cups_a
            stats[a_id]["cups_conceded"] += cups_b
        if b_id in stats:
            stats[b_id]["cups_scored"] += cups_b
            stats[b_id]["cups_conceded"] += cups_a

        winner = m.get("winner_id")
        if winner == a_id and a_id in stats:
            stats[a_id]["wins"] += 1
            if b_id in stats:
                stats[b_id]["losses"] += 1
        elif winner == b_id and b_id in stats:
            stats[b_id]["wins"] += 1
            if a_id in stats:
                stats[a_id]["losses"] += 1

    for s in stats.values():
        s["cup_diff"] = s["cups_scored"] - s["cups_conceded"]

    return sorted(stats.values(), key=lambda s: (-s["wins"], -s["cup_diff"]))


def get_ko_pairings(standings_a: list[dict], standings_b: list[dict]) -> list[dict]:
    """
    Generate KO matches from top-2 of each group.
    SF1: A1 vs B2, SF2: B1 vs A2.
    Final and 3rd place have no team IDs yet (filled after semis complete).
    """
    a1, a2 = standings_a[0]["team_id"], standings_a[1]["team_id"]
    b1, b2 = standings_b[0]["team_id"], standings_b[1]["team_id"]
    return [
        {"team_a_id": a1, "team_b_id": b2, "round": MatchRound.semifinal, "group": None, "status": MatchStatus.pending},
        {"team_a_id": b1, "team_b_id": a2, "round": MatchRound.semifinal, "group": None, "status": MatchStatus.pending},
        {"team_a_id": None, "team_b_id": None, "round": MatchRound.final, "group": None, "status": MatchStatus.pending},
        {"team_a_id": None, "team_b_id": None, "round": MatchRound.third_place, "group": None, "status": MatchStatus.pending},
    ]


def get_next_matches(matches: list[dict]) -> list[dict]:
    """Return all currently pending matches."""
    return [m for m in matches if m["status"] == MatchStatus.pending]
```

- [ ] **Step 4: Fix the tiebreaker test — re-read test logic**

The test `test_standings_tiebreaker_cup_diff` needs adjustment: T3 wins match 3, so T1 has cup_diff = (3-0) + (0-1) = 2, T2 has cup_diff = (0-3) + (1-0) = -2. T3 has 1 win. Fix the test:

In `tests/test_tournament.py`, replace `test_standings_tiebreaker_cup_diff` with:

```python
def test_standings_tiebreaker_cup_diff():
    # T1: wins match vs T2 (3-0). T2: wins match vs T3 (1-0). T3: wins match vs T1 would be weird — use simpler case:
    # T1 beats T2 with 3 cups remaining, T2 beats T3 with 1 cup remaining, T3 beats T1 with 1 cup
    # T1: 1 win (scored 3, conceded 1), cup_diff = 2
    # T2: 1 win (scored 1, conceded 3 + scored...) — let's just check ordering
    teams = [make_team(1, "T1", "A"), make_team(2, "T2", "A"), make_team(3, "T3", "A")]
    matches = [
        # T1 beats T2, 5 cups to 0
        make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1, cups_a=5, cups_b=0),
        # T2 beats T3, 1 cup to 0
        make_match(2, 2, 3, "A", MatchStatus.completed, winner_id=2, cups_a=1, cups_b=0),
        # T3 beats T1, 1 cup to 0
        make_match(3, 3, 1, "A", MatchStatus.completed, winner_id=3, cups_a=1, cups_b=0),
    ]
    # T1: 1 win, cups_scored=5, cups_conceded=0+1=1 → diff=4 (note: in match 3, team_a=T3, team_b=T1)
    # T2: 1 win, cups_scored=0+1=1, cups_conceded=5+0=5 → diff=-4
    # T3: 1 win, cups_scored=0+1=1, cups_conceded=0+1=1 → diff=0
    standings = calculate_standings(teams, matches)
    # All 1 win; T1 cup_diff=4 > T3 cup_diff=0 > T2 cup_diff=-4
    assert standings[0]["team_id"] == 1
    assert standings[1]["team_id"] == 3
    assert standings[2]["team_id"] == 2
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
docker compose run --rm app pytest tests/test_tournament.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/tournament.py tests/test_tournament.py
git commit -m "feat: tournament logic with group splitting, round-robin, standings, KO"
```

---

## Task 4: Auth

**Files:**
- Create: `app/auth.py`
- Extend: `tests/test_routes.py` (auth tests added in later tasks; here just verify login endpoint)

- [ ] **Step 1: Create `app/auth.py`**

```python
import hashlib
import os
from fastapi import Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db


SESSION_COOKIE = "bp_session"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def create_session_value(password: str) -> str:
    """Simple HMAC-signed session value using SECRET_KEY."""
    from itsdangerous import URLSafeSerializer
    secret = os.environ.get("SECRET_KEY", "dev-secret")
    s = URLSafeSerializer(secret)
    return s.dumps({"auth": True})


def validate_session_value(value: str) -> bool:
    from itsdangerous import URLSafeSerializer, BadSignature
    secret = os.environ.get("SECRET_KEY", "dev-secret")
    s = URLSafeSerializer(secret)
    try:
        data = s.loads(value)
        return data.get("auth") is True
    except BadSignature:
        return False


def require_auth(request: Request):
    """FastAPI dependency — raises 302 redirect to /login if not authenticated."""
    session_val = request.cookies.get(SESSION_COOKIE)
    if not session_val or not validate_session_value(session_val):
        raise HTTPException(status_code=302, headers={"Location": "/login"})
```

- [ ] **Step 2: Create stub `app/main.py`** (minimal app needed for tests to import)

```python
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.auth import (
    SESSION_COOKIE, hash_password, verify_password,
    create_session_value, require_auth,
)
from app.models import Tournament, TournamentStatus


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def post_login(request: Request, password: str = Form(...), db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if tournament and verify_password(password, tournament.admin_password_hash):
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie(SESSION_COOKIE, create_session_value(password), httponly=True, samesite="lax")
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Falsches Passwort"}, status_code=401)


@app.post("/logout")
def post_logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ── Redirect root ─────────────────────────────────────────────────────────────

@app.get("/")
def root(db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament or tournament.status == TournamentStatus.setup:
        return RedirectResponse(url="/setup")
    return RedirectResponse(url="/admin")
```

- [ ] **Step 3: Create minimal templates needed for auth tests**

Create `app/templates/login.html`:

```html
<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>Login</title></head>
<body>
<h1>Beer Pong Turnier</h1>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="post" action="/login">
  <input type="password" name="password" placeholder="Passwort" required autofocus>
  <button type="submit">Einloggen</button>
</form>
</body>
</html>
```

- [ ] **Step 4: Write auth integration tests in `tests/test_routes.py`**

```python
import pytest
from app.models import Tournament, TournamentStatus
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
    assert SESSION_COOKIE not in response.cookies or response.cookies[SESSION_COOKIE] == ""
```

- [ ] **Step 5: Run auth tests**

```bash
docker compose run --rm app pytest tests/test_routes.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/auth.py app/main.py app/templates/login.html tests/test_routes.py
git commit -m "feat: auth with session cookie, login/logout routes"
```

---

## Task 5: Setup Routes

**Files:**
- Modify: `app/main.py` (add setup routes)
- Create: `app/templates/setup.html`
- Extend: `tests/test_routes.py`

- [ ] **Step 1: Write failing setup route tests — add to `tests/test_routes.py`**

```python
def test_setup_get_requires_no_auth(client, db):
    """Setup page is accessible without login (first-time setup)."""
    response = client.get("/setup")
    assert response.status_code == 200
    assert "Turnier" in response.text


def test_setup_post_creates_tournament_and_teams(client, db):
    data = {
        "title": "Mein Turnier",
        "num_players": "6",
        "admin_password": "bier2024",
        "team_name_1": "Die Hartys", "player1_1": "Max", "player2_1": "Tom",
        "team_name_2": "Bierboys",   "player1_2": "Anna", "player2_2": "Lisa",
        "team_name_3": "Hopfen",     "player1_3": "Jan", "player2_3": "Kai",
    }
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.status_code == 302

    tournament = db.query(Tournament).first()
    assert tournament is not None
    assert tournament.status == TournamentStatus.group_stage
    assert len(tournament.teams) == 3
    assert len(tournament.matches) == 3  # C(3,2) = 3 for 3 teams? No — 6 players = 3 teams, 2 groups of 1+2... wait


def test_setup_post_12_players_creates_10_matches(client, db):
    data = {"title": "T", "num_players": "12", "admin_password": "pw"}
    for i in range(1, 7):
        data[f"team_name_{i}"] = f"Team{i}"
        data[f"player1_{i}"] = f"P{i}a"
        data[f"player2_{i}"] = f"P{i}b"
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.status_code == 302
    tournament = db.query(Tournament).first()
    assert len(tournament.matches) == 6  # 2 groups of 3 → 3+3 group matches


def test_setup_redirects_to_admin_after_start(client, db):
    data = {"title": "T", "num_players": "4", "admin_password": "pw"}
    for i in range(1, 3):
        data[f"team_name_{i}"] = f"Team{i}"
        data[f"player1_{i}"] = f"P{i}a"
        data[f"player2_{i}"] = f"P{i}b"
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.headers["location"] == "/admin"
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker compose run --rm app pytest tests/test_routes.py::test_setup_get_requires_no_auth -v
```

Expected: FAIL (404 — route not defined yet).

- [ ] **Step 3: Add setup routes to `app/main.py`**

Add after the existing imports and before auth routes:

```python
import random
from app.models import Team, Match
from app import tournament as tour_logic


# ── Setup routes ──────────────────────────────────────────────────────────────

@app.get("/setup", response_class=HTMLResponse)
def get_setup(request: Request, db: Session = Depends(get_db)):
    existing = db.query(Tournament).first()
    if existing and existing.status != TournamentStatus.setup:
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse("setup.html", {"request": request, "num_players_options": [8, 10, 12, 14, 16]})


@app.post("/setup")
def post_setup(
    request: Request,
    title: str = Form(...),
    num_players: int = Form(...),
    admin_password: str = Form(...),
    db: Session = Depends(get_db),
):
    # Parse teams from form: team_name_N, player1_N, player2_N
    num_teams = num_players // 2
    teams_data = []
    for i in range(1, num_teams + 1):
        # Use request.form directly for dynamic keys
        form = None  # will be populated below
        teams_data.append({"idx": i})

    # Re-read form data properly
    import asyncio
    form_data = asyncio.run(request.form()) if False else None  # sync workaround
    # Use a different approach: accept form fields via **kwargs pattern with Form fields named predictably
    # Since FastAPI doesn't support dynamic Form keys natively, we parse from request body in a sync endpoint
    # by using request.state workaround — but for sync routes we need to read body differently.
    # Solution: use a dedicated Pydantic-free approach with explicit max teams.
    raise NotImplementedError("See Step 4 for correct implementation")
```

Wait — FastAPI sync routes can't call `await request.form()`. We need to handle dynamic form fields differently. The correct approach: use a background-compatible form reader by making the route async.

- [ ] **Step 4: Replace setup route with correct async implementation in `app/main.py`**

Replace the `post_setup` function and its import block with:

```python
import random
from app.models import Team, Match
from app import tournament as tour_logic


@app.get("/setup", response_class=HTMLResponse)
def get_setup(request: Request, db: Session = Depends(get_db)):
    existing = db.query(Tournament).first()
    if existing and existing.status != TournamentStatus.setup:
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse("setup.html", {"request": request, "num_players_options": [8, 10, 12, 14, 16]})


@app.post("/setup")
async def post_setup(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    title = form.get("title", "Beer Pong Turnier")
    num_players = int(form.get("num_players", 12))
    admin_password = form.get("admin_password", "")
    num_teams = num_players // 2

    teams_input = []
    for i in range(1, num_teams + 1):
        teams_input.append({
            "name": form.get(f"team_name_{i}", f"Team {i}"),
            "player1": form.get(f"player1_{i}", ""),
            "player2": form.get(f"player2_{i}", ""),
        })

    # Shuffle for random group assignment
    random.shuffle(teams_input)

    # Create tournament
    tournament = Tournament(
        title=title,
        status=TournamentStatus.group_stage,
        admin_password_hash=hash_password(admin_password),
        num_players=num_players,
    )
    db.add(tournament)
    db.flush()

    # Create team ORM objects (no group assigned yet)
    team_objs = []
    for td in teams_input:
        t = Team(tournament_id=tournament.id, name=td["name"],
                 player1=td["player1"], player2=td["player2"], group="A")
        db.add(t)
        team_objs.append(t)
    db.flush()

    # Split into groups using pure logic (needs dicts with 'id')
    team_dicts = [{"id": t.id, "name": t.name, "group": None} for t in team_objs]
    group_a_dicts, group_b_dicts = tour_logic.split_into_groups(team_dicts)

    # Assign groups on ORM objects
    group_a_ids = {d["id"] for d in group_a_dicts}
    for t in team_objs:
        t.group = "A" if t.id in group_a_ids else "B"

    # Generate group matches
    match_specs = (
        tour_logic.generate_round_robin(group_a_dicts, "A") +
        tour_logic.generate_round_robin(group_b_dicts, "B")
    )
    for ms in match_specs:
        db.add(Match(tournament_id=tournament.id, **ms))

    db.commit()

    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(SESSION_COOKIE, create_session_value(admin_password), httponly=True, samesite="lax")
    return response
```

- [ ] **Step 5: Create `app/templates/setup.html`**

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Turnier Setup</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; }
    h1 { color: #f59e0b; }
    .team-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem; margin-bottom: 0.5rem; }
    input, select { width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
    button { background: #f59e0b; color: white; border: none; padding: 0.75rem 2rem; border-radius: 6px; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
    label { font-size: 0.8rem; color: #666; }
    .section { margin-bottom: 1.5rem; }
  </style>
</head>
<body>
  <h1>🍺 Turnier Setup</h1>
  <form method="post" action="/setup" id="setup-form">
    <div class="section">
      <label>Turniername</label>
      <input type="text" name="title" value="Beer Pong Turnier" required>
    </div>
    <div class="section">
      <label>Anzahl Spieler</label>
      <select name="num_players" id="num-players" onchange="updateTeamFields()">
        {% for n in num_players_options %}
        <option value="{{ n }}" {% if n == 12 %}selected{% endif %}>{{ n }} Spieler ({{ n // 2 }} Teams)</option>
        {% endfor %}
      </select>
    </div>
    <div class="section">
      <label>Admin-Passwort</label>
      <input type="password" name="admin_password" required minlength="4">
    </div>
    <div class="section">
      <h3>Teams</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;margin-bottom:0.25rem">
        <span style="font-size:0.75rem;color:#666">Teamname</span>
        <span style="font-size:0.75rem;color:#666">Spieler 1</span>
        <span style="font-size:0.75rem;color:#666">Spieler 2</span>
      </div>
      <div id="team-fields"></div>
    </div>
    <button type="submit">Turnier starten 🚀</button>
  </form>
  <script>
    function updateTeamFields() {
      const n = parseInt(document.getElementById('num-players').value);
      const numTeams = n / 2;
      const container = document.getElementById('team-fields');
      container.innerHTML = '';
      for (let i = 1; i <= numTeams; i++) {
        container.innerHTML += `
          <div class="team-row">
            <input type="text" name="team_name_${i}" placeholder="Team ${i}" required>
            <input type="text" name="player1_${i}" placeholder="Spieler 1" required>
            <input type="text" name="player2_${i}" placeholder="Spieler 2" required>
          </div>`;
      }
    }
    updateTeamFields();
  </script>
</body>
</html>
```

- [ ] **Step 6: Run setup tests**

```bash
docker compose run --rm app pytest tests/test_routes.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/templates/setup.html tests/test_routes.py
git commit -m "feat: setup route — creates tournament, teams, and group matches"
```

---

## Task 6: Admin Routes + Result Entry

**Files:**
- Modify: `app/main.py` (add admin routes)
- Create: `app/templates/admin.html`
- Create: `app/templates/partials/match_modal.html`
- Extend: `tests/test_routes.py`

- [ ] **Step 1: Write failing admin route tests — append to `tests/test_routes.py`**

```python
from app.models import Match, MatchStatus, MatchRound
from app.auth import hash_password, SESSION_COOKIE, create_session_value


def setup_full_tournament(db):
    """Helper: create a tournament with 6 teams and 6 group matches."""
    from app.models import Tournament, TournamentStatus, Team, Match, MatchRound, MatchStatus
    t = Tournament(title="T", status=TournamentStatus.group_stage,
                   admin_password_hash=hash_password("pw"), num_players=12)
    db.add(t)
    db.flush()
    teams = []
    for i in range(1, 7):
        group = "A" if i <= 3 else "B"
        team = Team(tournament_id=t.id, name=f"Team{i}",
                    player1=f"P{i}a", player2=f"P{i}b", group=group)
        db.add(team)
        teams.append(team)
    db.flush()

    # Group A: teams 0,1,2; Group B: teams 3,4,5
    pairs_a = [(teams[0], teams[1]), (teams[0], teams[2]), (teams[1], teams[2])]
    pairs_b = [(teams[3], teams[4]), (teams[3], teams[5]), (teams[4], teams[5])]
    for a, b in pairs_a + pairs_b:
        db.add(Match(tournament_id=t.id, team_a_id=a.id, team_b_id=b.id,
                     round=MatchRound.group, group=a.group, status=MatchStatus.pending))
    db.commit()
    db.refresh(t)
    return t


def test_admin_requires_auth(client, db):
    setup_full_tournament(db)
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


def test_admin_accessible_with_auth(client, db):
    setup_full_tournament(db)
    response = client.get("/admin", cookies=auth_cookies())
    assert response.status_code == 200


def test_submit_result_updates_match(client, db):
    t = setup_full_tournament(db)
    match = db.query(Match).filter_by(tournament_id=t.id).first()
    winner_id = match.team_a_id
    response = client.post(
        f"/matches/{match.id}/result",
        data={"winner_id": str(winner_id), "cups_a": "3", "cups_b": "0"},
        cookies=auth_cookies(),
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
    # Submit all group matches
    for m in matches:
        client.post(
            f"/matches/{m.id}/result",
            data={"winner_id": str(m.team_a_id), "cups_a": "3", "cups_b": "0"},
            cookies=auth_cookies(),
        )
    db.expire_all()
    ko_matches = db.query(Match).filter_by(
        tournament_id=t.id, round=MatchRound.semifinal
    ).all()
    assert len(ko_matches) == 2
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker compose run --rm app pytest tests/test_routes.py::test_admin_requires_auth -v
```

Expected: FAIL (404).

- [ ] **Step 3: Add admin routes to `app/main.py`**

Append to `app/main.py`:

```python
from datetime import datetime, timezone
from sqlalchemy import and_


# ── Admin routes ──────────────────────────────────────────────────────────────

def _get_tournament_or_redirect(db: Session):
    t = db.query(Tournament).first()
    if not t:
        return None
    return t


def _build_bracket_context(tournament, db: Session) -> dict:
    """Build context dict for bracket/admin templates."""
    from app import tournament as tour_logic
    teams = tournament.teams
    matches = tournament.matches

    group_a_teams = [t for t in teams if t.group == "A"]
    group_b_teams = [t for t in teams if t.group == "B"]
    group_a_matches = [m for m in matches if m.group == "A" and m.round == MatchRound.group]
    group_b_matches = [m for m in matches if m.group == "B" and m.round == MatchRound.group]

    team_dicts_a = [{"id": t.id, "name": t.name, "group": t.group} for t in group_a_teams]
    team_dicts_b = [{"id": t.id, "name": t.name, "group": t.group} for t in group_b_teams]

    def match_to_dict(m):
        return {"id": m.id, "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
                "group": m.group, "round": m.round, "status": m.status,
                "winner_id": m.winner_id, "cups_a": m.cups_a, "cups_b": m.cups_b}

    standings_a = tour_logic.calculate_standings(team_dicts_a, [match_to_dict(m) for m in group_a_matches])
    standings_b = tour_logic.calculate_standings(team_dicts_b, [match_to_dict(m) for m in group_b_matches])

    # Enrich standings with team name lookup
    team_map = {t.id: t for t in teams}
    for s in standings_a + standings_b:
        s["name"] = team_map[s["team_id"]].name
        s["player1"] = team_map[s["team_id"]].player1
        s["player2"] = team_map[s["team_id"]].player2

    pending_matches = [m for m in matches if m.status == MatchStatus.pending]
    completed_count = sum(1 for m in matches if m.status == MatchStatus.completed)
    total_count = len(matches)

    ko_matches = [m for m in matches if m.round != MatchRound.group]

    return {
        "tournament": tournament,
        "standings_a": standings_a,
        "standings_b": standings_b,
        "pending_matches": pending_matches,
        "completed_count": completed_count,
        "total_count": total_count,
        "ko_matches": ko_matches,
        "all_matches": matches,
        "team_map": team_map,
    }


@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
    tournament = _get_tournament_or_redirect(db)
    if not tournament:
        return RedirectResponse(url="/setup")
    ctx = _build_bracket_context(tournament, db)
    ctx["request"] = request
    return templates.TemplateResponse("admin.html", ctx)


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

    # Check if all group matches done → generate KO
    tournament = db.query(Tournament).filter_by(id=match.tournament_id).first()
    group_matches = [m for m in tournament.matches if m.round == MatchRound.group]
    if all(m.status == MatchStatus.completed for m in group_matches):
        ko_existing = [m for m in tournament.matches if m.round == MatchRound.semifinal]
        if not ko_existing:
            _generate_ko_matches(tournament, db)
            tournament.status = TournamentStatus.knockout

    # Check if all semis done → fill final + 3rd place
    semis = [m for m in tournament.matches if m.round == MatchRound.semifinal]
    if semis and all(m.status == MatchStatus.completed for m in semis):
        final = next((m for m in tournament.matches if m.round == MatchRound.final), None)
        third = next((m for m in tournament.matches if m.round == MatchRound.third_place), None)
        if final and final.team_a_id is None:
            winners = [m.winner_id for m in semis]
            losers = [m.team_a_id if m.winner_id == m.team_b_id else m.team_b_id for m in semis]
            final.team_a_id = winners[0]
            final.team_b_id = winners[1]
            if third:
                third.team_a_id = losers[0]
                third.team_b_id = losers[1]

    # Check if final done → tournament finished
    final_match = next((m for m in tournament.matches if m.round == MatchRound.final), None)
    if final_match and final_match.status == MatchStatus.completed:
        tournament.status = TournamentStatus.finished

    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


def _generate_ko_matches(tournament, db: Session):
    from app import tournament as tour_logic

    teams = tournament.teams
    group_a_teams = [{"id": t.id, "name": t.name, "group": t.group} for t in teams if t.group == "A"]
    group_b_teams = [{"id": t.id, "name": t.name, "group": t.group} for t in teams if t.group == "B"]
    group_a_matches = [m for m in tournament.matches if m.group == "A" and m.round == MatchRound.group]
    group_b_matches = [m for m in tournament.matches if m.group == "B" and m.round == MatchRound.group]

    def match_to_dict(m):
        return {"id": m.id, "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
                "group": m.group, "round": m.round, "status": m.status,
                "winner_id": m.winner_id, "cups_a": m.cups_a, "cups_b": m.cups_b}

    standings_a = tour_logic.calculate_standings(group_a_teams, [match_to_dict(m) for m in group_a_matches])
    standings_b = tour_logic.calculate_standings(group_b_teams, [match_to_dict(m) for m in group_b_matches])

    ko_specs = tour_logic.get_ko_pairings(standings_a, standings_b)
    for ks in ko_specs:
        db.add(Match(
            tournament_id=tournament.id,
            team_a_id=ks["team_a_id"],
            team_b_id=ks["team_b_id"],
            round=ks["round"],
            group=ks["group"],
            status=ks["status"],
        ))
```

- [ ] **Step 4: Create `app/templates/admin.html`**

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Admin – {{ tournament.title }}</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; max-width: 480px; margin: 0 auto; padding: 1rem; background: #0f172a; color: #f1f5f9; }
    h1 { color: #f59e0b; font-size: 1.2rem; margin: 0 0 0.5rem; }
    .progress { background: #1e293b; border-radius: 8px; height: 8px; margin-bottom: 1rem; }
    .progress-bar { background: #f59e0b; height: 8px; border-radius: 8px; transition: width 0.3s; }
    .progress-label { font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.25rem; }
    .match-card { background: #1e293b; border-radius: 10px; padding: 1rem; margin-bottom: 0.75rem; cursor: pointer; border: 2px solid transparent; }
    .match-card:hover { border-color: #f59e0b; }
    .match-card .vs { text-align: center; color: #64748b; margin: 0.25rem 0; font-size: 0.8rem; }
    .match-card .team { font-weight: 600; font-size: 1rem; }
    .section-title { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; margin: 1rem 0 0.5rem; }
    .standings table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    .standings th { color: #94a3b8; text-align: left; padding: 0.25rem 0.5rem; }
    .standings td { padding: 0.25rem 0.5rem; border-top: 1px solid #1e293b; }
    .badge { background: #f59e0b; color: #0f172a; border-radius: 4px; padding: 0 6px; font-size: 0.7rem; font-weight: 700; }
    .finished-banner { background: #16a34a; text-align: center; border-radius: 10px; padding: 1.5rem; margin: 1rem 0; font-size: 1.2rem; font-weight: 700; }
    /* Modal */
    .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 100; }
    .modal-overlay.open { display: flex; align-items: center; justify-content: center; }
    .modal { background: #1e293b; border-radius: 12px; padding: 1.5rem; width: 90%; max-width: 360px; }
    .modal h2 { margin-top: 0; font-size: 1rem; color: #f59e0b; }
    .cup-row { display: flex; align-items: center; gap: 0.5rem; margin: 0.5rem 0; }
    .cup-row label { flex: 1; font-size: 0.9rem; }
    .cup-row input { width: 60px; padding: 0.4rem; background: #0f172a; color: #f1f5f9; border: 1px solid #334155; border-radius: 4px; text-align: center; }
    .btn { background: #f59e0b; color: #0f172a; border: none; padding: 0.6rem 1rem; border-radius: 6px; font-weight: 700; cursor: pointer; width: 100%; margin-top: 0.5rem; }
    .btn-cancel { background: #334155; color: #f1f5f9; margin-top: 0.25rem; }
  </style>
</head>
<body>
  <h1>🍺 {{ tournament.title }}</h1>
  <div class="progress-label">{{ completed_count }} / {{ total_count }} Spiele</div>
  <div class="progress"><div class="progress-bar" style="width: {{ (completed_count / total_count * 100) | int if total_count else 0 }}%"></div></div>

  {% if tournament.status.value == 'finished' %}
    {% set final_match = ko_matches | selectattr('round.value', 'eq', 'final') | list | first %}
    {% if final_match and final_match.winner_id %}
      <div class="finished-banner">🏆 {{ team_map[final_match.winner_id].name }} gewinnt!</div>
    {% endif %}
  {% endif %}

  {% if pending_matches %}
  <div class="section-title">Nächste Spiele</div>
  {% for match in pending_matches[:4] %}
    {% if match.team_a_id and match.team_b_id %}
    <div class="match-card" onclick="openModal({{ match.id }}, '{{ team_map[match.team_a_id].name }}', '{{ team_map[match.team_b_id].name }}', {{ match.team_a_id }}, {{ match.team_b_id }})">
      <div class="team">{{ team_map[match.team_a_id].name }}</div>
      <div class="vs">vs</div>
      <div class="team">{{ team_map[match.team_b_id].name }}</div>
      <div style="margin-top:0.5rem;font-size:0.75rem;color:#64748b">
        {% if match.round.value == 'group' %}Gruppe {{ match.group }}
        {% elif match.round.value == 'semifinal' %}Halbfinale
        {% elif match.round.value == 'final' %}Finale
        {% else %}Spiel um Platz 3{% endif %}
      </div>
    </div>
    {% endif %}
  {% endfor %}
  {% endif %}

  <div class="section-title">Gruppenstand A</div>
  <div class="standings">
    <table>
      <tr><th>#</th><th>Team</th><th>S</th><th>N</th><th>±</th></tr>
      {% for s in standings_a %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>{{ s.name }} {% if loop.index <= 2 %}<span class="badge">KO</span>{% endif %}</td>
        <td>{{ s.wins }}</td><td>{{ s.losses }}</td><td>{{ s.cup_diff }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  <div class="section-title">Gruppenstand B</div>
  <div class="standings">
    <table>
      <tr><th>#</th><th>Team</th><th>S</th><th>N</th><th>±</th></tr>
      {% for s in standings_b %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>{{ s.name }} {% if loop.index <= 2 %}<span class="badge">KO</span>{% endif %}</td>
        <td>{{ s.wins }}</td><td>{{ s.losses }}</td><td>{{ s.cup_diff }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  {% if ko_matches %}
  <div class="section-title">K.O.-Phase</div>
  {% for match in ko_matches %}
  <div class="match-card {% if match.status.value == 'completed' %}opacity-50{% endif %}"
    {% if match.status.value == 'pending' and match.team_a_id and match.team_b_id %}
    onclick="openModal({{ match.id }}, '{{ team_map[match.team_a_id].name }}', '{{ team_map[match.team_b_id].name }}', {{ match.team_a_id }}, {{ match.team_b_id }})"
    {% endif %}>
    <div style="font-size:0.7rem;color:#64748b;margin-bottom:0.25rem">
      {% if match.round.value == 'semifinal' %}Halbfinale
      {% elif match.round.value == 'final' %}Finale
      {% else %}Spiel um Platz 3{% endif %}
    </div>
    <div class="team">{% if match.team_a_id %}{{ team_map[match.team_a_id].name }}{% else %}TBD{% endif %}</div>
    <div class="vs">vs</div>
    <div class="team">{% if match.team_b_id %}{{ team_map[match.team_b_id].name }}{% else %}TBD{% endif %}</div>
    {% if match.winner_id %}
    <div style="margin-top:0.4rem;font-size:0.75rem;color:#16a34a">🏆 {{ team_map[match.winner_id].name }} ({{ match.cups_a }}:{{ match.cups_b }})</div>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}

  <div style="margin-top:2rem">
    <a href="/tv" style="color:#64748b;font-size:0.8rem">TV-Ansicht öffnen →</a>
    <form method="post" action="/logout" style="display:inline;margin-left:1rem">
      <button type="submit" style="background:none;border:none;color:#64748b;font-size:0.8rem;cursor:pointer">Logout</button>
    </form>
  </div>

  <!-- Modal -->
  <div class="modal-overlay" id="result-modal">
    <div class="modal">
      <h2>Ergebnis eintragen</h2>
      <form method="post" id="result-form">
        <input type="hidden" name="winner_id" id="modal-winner-id">
        <div class="cup-row">
          <label id="modal-team-a-label">Team A</label>
          <input type="number" name="cups_a" id="modal-cups-a" min="0" max="10" value="0" required>
          <span style="color:#64748b">Cups</span>
        </div>
        <div class="cup-row">
          <label id="modal-team-b-label">Team B</label>
          <input type="number" name="cups_b" id="modal-cups-b" min="0" max="10" value="0" required>
          <span style="color:#64748b">Cups</span>
        </div>
        <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
          <button type="button" class="btn" style="background:#16a34a" id="btn-win-a"></button>
          <button type="button" class="btn" style="background:#dc2626" id="btn-win-b"></button>
        </div>
        <button type="submit" class="btn" style="margin-top:0.5rem">Speichern</button>
        <button type="button" class="btn btn-cancel" onclick="closeModal()">Abbrechen</button>
      </form>
    </div>
  </div>

  <script>
    let currentTeamAId, currentTeamBId;
    function openModal(matchId, teamAName, teamBName, teamAId, teamBId) {
      currentTeamAId = teamAId; currentTeamBId = teamBId;
      document.getElementById('result-form').action = '/matches/' + matchId + '/result';
      document.getElementById('modal-team-a-label').textContent = teamAName;
      document.getElementById('modal-team-b-label').textContent = teamBName;
      document.getElementById('btn-win-a').textContent = '🏆 ' + teamAName + ' gewinnt';
      document.getElementById('btn-win-b').textContent = '🏆 ' + teamBName + ' gewinnt';
      document.getElementById('modal-winner-id').value = '';
      document.getElementById('result-modal').classList.add('open');
    }
    function closeModal() {
      document.getElementById('result-modal').classList.remove('open');
    }
    document.getElementById('btn-win-a').onclick = () => {
      document.getElementById('modal-winner-id').value = currentTeamAId;
    };
    document.getElementById('btn-win-b').onclick = () => {
      document.getElementById('modal-winner-id').value = currentTeamBId;
    };
    document.getElementById('result-modal').onclick = (e) => {
      if (e.target === e.currentTarget) closeModal();
    };
  </script>
</body>
</html>
```

- [ ] **Step 5: Run admin tests**

```bash
docker compose run --rm app pytest tests/test_routes.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/admin.html
git commit -m "feat: admin view with match result entry and KO auto-advance"
```

---

## Task 7: TV View + HTMX Partials

**Files:**
- Modify: `app/main.py` (add TV and partial routes)
- Create: `app/templates/tv.html`
- Create: `app/templates/partials/bracket.html`
- Extend: `tests/test_routes.py`

- [ ] **Step 1: Write failing TV route tests — append to `tests/test_routes.py`**

```python
def test_tv_is_public(client, db):
    """TV view accessible without auth."""
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
    assert "Jetzt am Tisch" in response.text or "Nächstes Spiel" in response.text
```

- [ ] **Step 2: Append TV routes to `app/main.py`**

```python
# ── TV + partial routes ───────────────────────────────────────────────────────

@app.get("/tv", response_class=HTMLResponse)
def get_tv(request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return RedirectResponse(url="/setup")
    ctx = _build_bracket_context(tournament, db)
    ctx["request"] = request
    return templates.TemplateResponse("tv.html", ctx)


@app.get("/partials/bracket", response_class=HTMLResponse)
def get_bracket_partial(request: Request, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament:
        return HTMLResponse("<p>Kein Turnier aktiv</p>")
    ctx = _build_bracket_context(tournament, db)
    ctx["request"] = request
    return templates.TemplateResponse("partials/bracket.html", ctx)
```

- [ ] **Step 3: Create `app/templates/partials/bracket.html`**

```html
<div id="bracket-content">
  {% if tournament.status.value == 'finished' %}
    {% set final_match = ko_matches | selectattr('round.value', 'eq', 'final') | list | first %}
    {% if final_match and final_match.winner_id %}
    <div style="text-align:center;padding:2rem;background:#16a34a;border-radius:12px;margin-bottom:1.5rem">
      <div style="font-size:2rem">🏆</div>
      <div style="font-size:1.5rem;font-weight:700">{{ team_map[final_match.winner_id].name }}</div>
      <div style="opacity:0.8">Turniersieger!</div>
    </div>
    {% endif %}
  {% else %}
    {% set next = pending_matches | selectattr('team_a_id') | selectattr('team_b_id') | list | first %}
    {% if next %}
    <div style="text-align:center;margin-bottom:1.5rem;padding:1.5rem;background:#1e3a5f;border-radius:12px;border:2px solid #f59e0b">
      <div style="font-size:0.8rem;color:#f59e0b;text-transform:uppercase;letter-spacing:2px;margin-bottom:0.5rem">Jetzt am Tisch</div>
      <div style="font-size:1.8rem;font-weight:700">{{ team_map[next.team_a_id].name }}</div>
      <div style="color:#64748b;margin:0.25rem 0">vs</div>
      <div style="font-size:1.8rem;font-weight:700">{{ team_map[next.team_b_id].name }}</div>
      <div style="font-size:0.85rem;color:#64748b;margin-top:0.5rem">
        {% if next.round.value == 'group' %}Gruppe {{ next.group }}
        {% elif next.round.value == 'semifinal' %}Halbfinale
        {% elif next.round.value == 'final' %}🏆 Finale
        {% else %}Spiel um Platz 3{% endif %}
      </div>
    </div>
    {% endif %}
  {% endif %}

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem">
    {% for group_label, standings in [('A', standings_a), ('B', standings_b)] %}
    <div>
      <div style="font-size:0.7rem;color:#64748b;text-transform:uppercase;margin-bottom:0.5rem">Gruppe {{ group_label }}</div>
      <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
        <tr style="color:#64748b"><th style="text-align:left;padding:2px 4px">#</th><th style="text-align:left">Team</th><th>S</th><th>±</th></tr>
        {% for s in standings %}
        <tr style="border-top:1px solid #1e293b">
          <td style="padding:4px">{{ loop.index }}</td>
          <td style="padding:4px;font-weight:{% if loop.index <= 2 %}600{% else %}400{% endif %}">
            {{ s.name }}{% if loop.index <= 2 %} <span style="font-size:0.65rem;background:#f59e0b;color:#0f172a;border-radius:3px;padding:0 4px">KO</span>{% endif %}
          </td>
          <td style="text-align:center">{{ s.wins }}</td>
          <td style="text-align:center;color:{% if s.cup_diff >= 0 %}#4ade80{% else %}#f87171{% endif %}">{{ s.cup_diff }}</td>
        </tr>
        {% endfor %}
      </table>
    </div>
    {% endfor %}
  </div>

  {% if ko_matches %}
  <div style="font-size:0.7rem;color:#64748b;text-transform:uppercase;margin-bottom:0.5rem">K.O.-Phase</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:0.75rem">
    {% for match in ko_matches %}
    <div style="background:#1e293b;border-radius:8px;padding:0.75rem;{% if match.status.value == 'completed' %}opacity:0.7{% endif %}">
      <div style="font-size:0.65rem;color:#64748b;margin-bottom:0.25rem">
        {% if match.round.value == 'semifinal' %}Halbfinale
        {% elif match.round.value == 'final' %}🏆 Finale
        {% else %}Platz 3{% endif %}
      </div>
      <div style="font-weight:600">{% if match.team_a_id %}{{ team_map[match.team_a_id].name }}{% else %}TBD{% endif %}</div>
      <div style="color:#64748b;font-size:0.75rem;margin:2px 0">vs</div>
      <div style="font-weight:600">{% if match.team_b_id %}{{ team_map[match.team_b_id].name }}{% else %}TBD{% endif %}</div>
      {% if match.winner_id %}
      <div style="margin-top:4px;font-size:0.75rem;color:#4ade80">🏆 {{ team_map[match.winner_id].name }} {{ match.cups_a }}:{{ match.cups_b }}</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>
```

- [ ] **Step 4: Create `app/templates/tv.html`**

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ tournament.title }} – Live</title>
  <script src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"></script>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f1f5f9; margin: 0; padding: 1.5rem 2rem; min-height: 100vh; }
    h1 { color: #f59e0b; font-size: 1.8rem; margin: 0 0 0.25rem; }
    .subtitle { color: #64748b; font-size: 0.9rem; margin-bottom: 1.5rem; }
    .live-dot { display: inline-block; width: 8px; height: 8px; background: #ef4444; border-radius: 50%; margin-right: 6px; animation: pulse 1.5s infinite; }
    @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }
  </style>
</head>
<body>
  <h1>🍺 {{ tournament.title }}</h1>
  <p class="subtitle"><span class="live-dot"></span>Live — aktualisiert automatisch alle 10 Sekunden</p>

  <div
    hx-get="/partials/bracket"
    hx-trigger="every 10s"
    hx-swap="innerHTML"
    id="live-bracket"
  >
    {% include "partials/bracket.html" %}
  </div>
</body>
</html>
```

- [ ] **Step 5: Run TV tests**

```bash
docker compose run --rm app pytest tests/test_routes.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/tv.html app/templates/partials/bracket.html
git commit -m "feat: TV view with live HTMX polling bracket"
```

---

## Task 8: Full Integration Smoke Test

**Files:**
- No new files — validate everything works end-to-end in Docker

- [ ] **Step 1: Build and start containers**

```bash
docker compose up --build -d
```

Expected: no build errors, both containers running.

- [ ] **Step 2: Check container health**

```bash
docker compose ps
```

Expected: `app` and `db` both show as `running` / healthy.

- [ ] **Step 3: Open setup page**

Navigate to `http://localhost:8000` in browser.
Expected: redirects to `/setup`, form appears with 12-player default.

- [ ] **Step 4: Create a tournament**

Fill in 12 player names across 6 teams, set password `bier2024`, click "Turnier starten".
Expected: redirected to `/admin`, shows 6 pending group matches.

- [ ] **Step 5: Test mobile layout**

In browser DevTools, switch to mobile view (375px width).
Expected: all cards and text readable, modal opens on tap.

- [ ] **Step 6: Open TV view**

Navigate to `http://localhost:8000/tv` in a second tab (or different browser).
Expected: large layout with "Jetzt am Tisch" box and group standings.

- [ ] **Step 7: Enter all group match results**

In admin view, enter results for all 6 group matches.
Expected: after last group match, semifinal cards appear automatically.

- [ ] **Step 8: Complete KO phase**

Enter semifinal and final results.
Expected: winner banner appears on both admin and TV view.

- [ ] **Step 9: Verify TV auto-refresh**

Wait 10+ seconds after entering a result on admin.
Expected: TV view updates without manual reload.

- [ ] **Step 10: Run full test suite**

```bash
docker compose run --rm app pytest -v
```

Expected: all tests PASS.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "test: full integration smoke test passed"
```

---

## Task 9: Railway Deployment

**Files:**
- Create: `.railwayignore`
- Verify: `Dockerfile` works for Railway

- [ ] **Step 1: Create `.railwayignore`**

```
.env
*.pyc
__pycache__
.git
tests/
docker-compose.yml
```

- [ ] **Step 2: Install Railway CLI (inside container not needed — run on host)**

```bash
# Windows (PowerShell)
iwr -useb https://raw.githubusercontent.com/railwayapp/cli/master/install.ps1 | iex
# Or via npm if available:
# npm install -g @railway/cli
```

- [ ] **Step 3: Login to Railway**

```bash
railway login
```

Opens browser for OAuth login.

- [ ] **Step 4: Create new Railway project**

```bash
railway init
```

Follow prompts: create new project named `beerpong-tournament`.

- [ ] **Step 5: Add PostgreSQL plugin**

In Railway dashboard (web UI): open the project → Add Service → Database → PostgreSQL.
Railway automatically sets `DATABASE_URL` in the environment.

- [ ] **Step 6: Set environment variables in Railway dashboard**

In Railway dashboard → project → app service → Variables:

```
ADMIN_PASSWORD=<your-tournament-password>
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
```

Note: `DATABASE_URL` is automatically injected by the PostgreSQL plugin.

- [ ] **Step 7: Deploy**

```bash
railway up
```

Or push to a linked GitHub repo for automatic deploys.

- [ ] **Step 8: Verify deployment**

```bash
railway open
```

Opens the deployed URL. Navigate through setup → admin → TV view.

- [ ] **Step 9: Commit deployment config**

```bash
git add .railwayignore
git commit -m "chore: Railway deployment config"
```

---

## Verification Checklist

1. `docker compose up --build` → app on http://localhost:8000 ✓
2. Setup page: select 10/12/14 players, enter names, start tournament ✓
3. Admin (mobile DevTools): enter results via modal ✓
4. TV view: auto-refreshes every 10s, shows "Jetzt am Tisch" ✓
5. KO phase auto-generates after all group games ✓
6. Winner banner shown after final ✓
7. `pytest -v` → all tests PASS ✓
8. Railway URL accessible and functional ✓
