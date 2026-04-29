# Setup Flow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static player-count dropdown with a dynamic mobile-friendly team-adding flow where player names are fully optional.

**Architecture:** JS-driven team cards in `setup.html` maintain a hidden `num_teams` counter. `post_setup` reads that counter instead of `num_players`. A SQLite migration makes `player1` nullable. All templates guard against `None` player names.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy, SQLite, vanilla JS

---

### Task 1: Make player columns nullable in model + DB migration

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py`

- [ ] **Step 1: Update the model**

In `app/models.py`, change `player1` to be optional (player2 is already nullable from a previous change):

```python
player1: Mapped[str | None] = mapped_column(String(50), nullable=True)
player2: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 2: Add SQLite migration**

SQLite cannot drop NOT NULL constraints via ALTER COLUMN. Add a table-recreation migration to `_run_migrations()` in `app/database.py`. Append after the existing migrations list:

```python
def _run_migrations():
    migrations = [
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS emoji VARCHAR(10) DEFAULT '🍺'",
        "ALTER TABLE tournaments ADD COLUMN IF NOT EXISTS current_match_id INTEGER",
        "ALTER TABLE tournaments ADD COLUMN IF NOT EXISTS next_match_id INTEGER",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            conn.execute(__import__("sqlalchemy").text(sql))
        conn.commit()

    # Make player1 and player2 nullable via table recreation (SQLite can't ALTER COLUMN)
    _migrate_teams_nullable_players()


def _migrate_teams_nullable_players():
    """Recreate teams table without NOT NULL on player1/player2, if needed."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        # Check if player1 is still NOT NULL by inspecting table info
        rows = conn.execute(sa.text("PRAGMA table_info(teams)")).fetchall()
        player1_row = next((r for r in rows if r[1] == "player1"), None)
        if player1_row is None or player1_row[3] == 0:
            # Column doesn't exist or already nullable — nothing to do
            return

        # Recreate without NOT NULL constraints on player columns
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS teams_new (
                id INTEGER NOT NULL PRIMARY KEY,
                tournament_id INTEGER REFERENCES tournaments(id),
                name VARCHAR(50),
                emoji VARCHAR(10) DEFAULT '🍺',
                player1 VARCHAR(50),
                player2 VARCHAR(50),
                "group" VARCHAR(1)
            )
        """))
        conn.execute(sa.text("""
            INSERT INTO teams_new (id, tournament_id, name, emoji, player1, player2, "group")
            SELECT id, tournament_id, name, emoji, player1, player2, "group" FROM teams
        """))
        conn.execute(sa.text("DROP TABLE teams"))
        conn.execute(sa.text("ALTER TABLE teams_new RENAME TO teams"))
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        conn.commit()
```

- [ ] **Step 3: Verify migration runs without error**

Start the app and check the logs for errors:
```
uvicorn app.main:app --reload
```
Expected: server starts, no migration errors in console.

- [ ] **Step 4: Commit**

```bash
git add app/models.py app/database.py
git commit -m "feat: make player1 and player2 nullable with SQLite migration"
```

---

### Task 2: Update `post_setup` to derive team count from form

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Replace num_players reading with num_teams**

In `app/main.py`, find `post_setup` and replace this block:

```python
num_players = int(form.get("num_players", 12))
num_teams = num_players // 2
initial_status = TournamentStatus.knockout if num_teams <= 4 else TournamentStatus.group_stage
```

With:

```python
num_teams = int(form.get("num_teams", 0))
initial_status = TournamentStatus.knockout if num_teams <= 4 else TournamentStatus.group_stage
```

- [ ] **Step 2: Replace teams_input construction**

Find and replace:

```python
teams_input = [
    {
        "name": form.get(f"team_name_{i}", f"Team {i}"),
        "emoji": form.get(f"emoji_{i}", "🍺"),
        "player1": form.get(f"player1_{i}", ""),
        "player2": form.get(f"player2_{i}", ""),
    }
    for i in range(1, num_teams + 1)
]
```

With (strips whitespace, stores None for empty optional fields):

```python
teams_input = []
for i in range(1, num_teams + 1):
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
```

Note: `initial_status` is reassigned here since `num_teams` may have changed after filtering empty names. Remove the earlier `initial_status` assignment from Step 1 and keep only this one:

Final top of `post_setup` should read:

```python
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
```

- [ ] **Step 3: Update Tournament creation to store num_teams * 2 as num_players**

The `Tournament` model still has `num_players`. Keep it for now, derive it:

```python
tournament = Tournament(
    title=title,
    status=initial_status,
    admin_password_hash=hash_password(admin_password),
    num_players=num_teams * 2,
)
```

- [ ] **Step 4: Update get_setup to remove num_players_options**

In `get_setup`:

```python
@app.get("/setup", response_class=HTMLResponse)
def get_setup(request: Request, db: Session = Depends(get_db)):
    existing = db.query(Tournament).first()
    if existing and existing.status != TournamentStatus.setup:
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse(request, "setup.html", {})
```

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: derive team count from dynamic form submission"
```

---

### Task 3: Update route tests for new form format

**Files:**
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Update test_setup_post_12_players_creates_6_group_matches**

This test submits `num_players: "12"`. Change it to use `num_teams: "6"` and remove player name fields (now optional):

```python
def test_setup_post_6_teams_creates_6_group_matches(client, db):
    data = {"title": "T", "num_teams": "6", "admin_password": "pw"}
    for i in range(1, 7):
        data[f"team_name_{i}"] = f"Team{i}"
        # player names intentionally omitted — they are now optional
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.status_code == 302
    tournament = db.query(Tournament).first()
    assert tournament is not None
    assert tournament.status == TournamentStatus.group_stage
    assert len(tournament.teams) == 6
    assert len(tournament.matches) == 6
```

- [ ] **Step 2: Update test_setup_redirects_to_admin**

Change to use 4 teams (the minimum for a valid tournament), and use `num_teams`:

```python
def test_setup_redirects_to_admin(client, db):
    data = {"title": "T", "num_teams": "4", "admin_password": "pw"}
    for i in range(1, 5):
        data[f"team_name_{i}"] = f"Team{i}"
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.headers["location"] == "/admin"
```

- [ ] **Step 3: Add test for optional player names**

```python
def test_setup_team_without_player_names(client, db):
    data = {"title": "T", "num_teams": "4", "admin_password": "pw"}
    for i in range(1, 5):
        data[f"team_name_{i}"] = f"Team{i}"
        # No player1_ or player2_ fields
    response = client.post("/setup", data=data, follow_redirects=False)
    assert response.status_code == 302
    team = db.query(Team).first()
    assert team.player1 is None
    assert team.player2 is None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_routes.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_routes.py
git commit -m "test: update setup route tests for dynamic team form"
```

---

### Task 4: Rewrite setup.html with dynamic team cards

**Files:**
- Modify: `app/templates/setup.html`

- [ ] **Step 1: Replace setup.html entirely**

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Turnier Setup – Beer Pong</title>
  <link rel="stylesheet" href="/static/css/style.css?v=2">
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <style>
    body { max-width: 800px; margin: 2rem auto; }
    @media (max-width: 900px) { body { margin: 0 auto !important; } }
    .admin-pass-section { max-width: 50%; }
    @media (max-width: 900px) { .admin-pass-section { max-width: 100%; } }
    .delete-btn {
      background: none; border: none; color: var(--danger);
      cursor: pointer; font-size: 1.1rem; padding: 0.25rem 0.5rem;
      opacity: 0.6; flex-shrink: 0;
    }
    .delete-btn:hover { opacity: 1; }
    #btn-start:disabled { opacity: 0.4; cursor: not-allowed; }
  </style>
</head>
<body>
  <div class="glass-panel">
    <h1>🍺 Turnier Setup</h1>
    <p style="color: var(--text-muted); margin-bottom: 2rem;">
      Lege den Turniernamen fest, trage alle Teams ein und starte das Turnier.
    </p>

    <form method="post" action="/setup" id="setup-form">
      <input type="hidden" name="num_teams" id="num-teams-count" value="0">

      <div class="grid-2 mb-4">
        <div class="section">
          <label>Turniername</label>
          <input type="text" name="title" value="Beer Pong Turnier" required>
        </div>
        <div class="section admin-pass-section">
          <label>Admin-Passwort</label>
          <input type="password" name="admin_password" required minlength="4"
                 placeholder="Wird für den Login benötigt">
        </div>
      </div>

      <div class="section mt-6">
        <h3 class="section-title">Teams</h3>
        <div id="team-fields" class="setup-grid"></div>
      </div>

      <button type="button" class="btn btn-secondary w-full mt-4"
              onclick="addTeam()" style="padding: 0.85rem; font-size: 1rem;">
        + Team hinzufügen
      </button>

      <button type="submit" id="btn-start" disabled
              class="btn btn-success w-full mt-4"
              style="padding: 1rem; font-size: 1.1rem;">
        Turnier starten 🚀
      </button>
      <p id="min-hint" style="text-align:center; font-size:0.75rem;
                               color:var(--text-muted); margin-top:0.5rem;">
        Mindestens 4 Teams erforderlich
      </p>
    </form>
  </div>

  <script>
    let teamCounter = 0;

    function addTeam() {
      teamCounter++;
      const idx = teamCounter;
      const container = document.getElementById('team-fields');
      const card = document.createElement('div');
      card.className = 'team-setup-card';
      card.id = `team-card-${idx}`;
      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <label style="color: var(--primary);" id="team-label-${idx}">Team ${teamCount()}</label>
          <button type="button" class="delete-btn" onclick="removeTeam(${idx})" title="Team entfernen">✕</button>
        </div>
        <div style="display:flex; flex-direction:column; gap:0.5rem; margin-top:0.5rem;">
          <div style="display:flex; gap:0.5rem;">
            <input type="text" name="emoji_${idx}" value="🍺" maxlength="2"
                   style="width:60px; text-align:center; font-size:1.2rem;" title="Emoji">
            <input type="text" name="team_name_${idx}" placeholder="Teamname" required
                   style="flex:1;" oninput="updateStartButton()">
          </div>
          <div class="flex-mobile-stack" style="display:flex; gap:0.5rem;">
            <input type="text" name="player1_${idx}" placeholder="Spieler 1 (optional)">
            <input type="text" name="player2_${idx}" placeholder="Spieler 2 (optional)">
          </div>
        </div>`;
      container.appendChild(card);
      updateIndices();
      updateStartButton();
      card.querySelector(`[name="team_name_${idx}"]`).focus();
    }

    function removeTeam(idx) {
      const card = document.getElementById(`team-card-${idx}`);
      if (card) card.remove();
      updateIndices();
      updateStartButton();
    }

    function teamCount() {
      return document.querySelectorAll('.team-setup-card').length;
    }

    function updateIndices() {
      const cards = document.querySelectorAll('.team-setup-card');
      cards.forEach((card, i) => {
        const label = card.querySelector('[id^="team-label-"]');
        if (label) label.textContent = `Team ${i + 1}`;
      });
      document.getElementById('num-teams-count').value = cards.length;
    }

    function updateStartButton() {
      const cards = document.querySelectorAll('.team-setup-card');
      const filled = [...cards].filter(card => {
        const inp = card.querySelector('input[name^="team_name_"]');
        return inp && inp.value.trim().length > 0;
      }).length;
      const btn = document.getElementById('btn-start');
      const hint = document.getElementById('min-hint');
      btn.disabled = filled < 4;
      hint.style.display = filled < 4 ? 'block' : 'none';
    }

    // Start with one empty card
    addTeam();
  </script>
</body>
</html>
```

- [ ] **Step 2: Manually test the form on mobile (or browser dev tools mobile view)**

- Open `http://localhost:8000/setup` (with `uvicorn app.main:app --reload`)
- Add 4+ teams, check that "Turnier starten" activates
- Delete a team, check labels renumber correctly
- Submit with some player names empty — tournament should start

- [ ] **Step 3: Commit**

```bash
git add app/templates/setup.html
git commit -m "feat: dynamic mobile-friendly setup form with optional player names"
```

---

### Task 5: Guard player name display in templates

**Files:**
- Modify: `app/templates/admin.html`
- Modify: `app/templates/partials/bracket.html`

Player names may now be `None`. Every place that renders `player1` or `player2` needs a guard.

- [ ] **Step 1: Fix overall_ranking team_players in main.py**

In `_build_bracket_context`, find three places that build `team_players` strings:

```python
# Line ~219 (winner):
"team_players": f"{w.player1} & {w.player2}" if w else "",
# Line ~226 (runner-up):
"team_players": f"{r.player1} & {r.player2}" if r else "",
# Line ~232/238 (3rd/4th):
"team_players": f"{t3.player1} & {t3.player2}" if t3 else "",
```

Replace all four occurrences with a helper. Add this function above `_build_bracket_context`:

```python
def _players_label(team) -> str:
    if not team:
        return ""
    parts = [p for p in (team.player1, team.player2) if p]
    return " & ".join(parts)
```

Then replace every `f"{t.player1} & {t.player2}" if t else ""` with `_players_label(t)`.

The four calls become:

```python
# in overall_ranking winner block:
"team_players": _players_label(w),
# runner-up:
"team_players": _players_label(r),
# 3rd:
"team_players": _players_label(t3),
# 4th:
"team_players": _players_label(t4),
```

Also fix the fallback in the group-stage remaining teams block:

```python
# find:
"team_players": f"{t.player1} & {t.player2}" if t else "",
# replace:
"team_players": _players_label(t),
```

- [ ] **Step 2: Fix standings player display in admin.html**

Find (appears twice, once for standings_a, once for standings_b):

```html
<div style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">{{ s.player1 }} & {{ s.player2 }}</div>
```

Replace both with:

```html
{% if s.player1 or s.player2 %}
<div style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">
  {{ s.player1 }}{% if s.player1 and s.player2 %} &amp; {% endif %}{{ s.player2 }}
</div>
{% endif %}
```

- [ ] **Step 3: Fix KO match player display in admin.html**

Find (appears for team_a and team_b in KO matches section):

```html
<div style="font-size: 0.75rem; color: var(--text-muted); font-weight: normal; margin-top: 2px;">{{ team_map[match.team_a_id].player1 }} & {{ team_map[match.team_a_id].player2 }}</div>
```

Replace with:

```html
{% set ta = team_map[match.team_a_id] %}
{% if ta.player1 or ta.player2 %}
<div style="font-size: 0.75rem; color: var(--text-muted); font-weight: normal; margin-top: 2px;">
  {{ ta.player1 }}{% if ta.player1 and ta.player2 %} &amp; {% endif %}{{ ta.player2 }}
</div>
{% endif %}
```

Do the same for `team_b`:

```html
{% set tb = team_map[match.team_b_id] %}
{% if tb.player1 or tb.player2 %}
<div style="font-size: 0.75rem; color: var(--text-muted); font-weight: normal; margin-top: 2px;">
  {{ tb.player1 }}{% if tb.player1 and tb.player2 %} &amp; {% endif %}{{ tb.player2 }}
</div>
{% endif %}
```

- [ ] **Step 4: Fix player display in bracket.html (TV view)**

Find (the "now playing" slide, team_a and team_b player lines):

```html
<div style="font-size:0.9rem;color:var(--text-muted);font-weight:400;margin-top:0.3rem;">{{ team_map[next.team_a_id].player1 }} & {{ team_map[next.team_a_id].player2 }}</div>
```

Replace with:

```html
{% set ta = team_map[next.team_a_id] %}
{% if ta.player1 or ta.player2 %}
<div style="font-size:0.9rem;color:var(--text-muted);font-weight:400;margin-top:0.3rem;">
  {{ ta.player1 }}{% if ta.player1 and ta.player2 %} &amp; {% endif %}{{ ta.player2 }}
</div>
{% endif %}
```

Do the same for `team_b_id` in that slide.

- [ ] **Step 5: Fix also in standings display in bracket.html**

Find in the standings slide:

```html
<div style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">{{ s.player1 }} & {{ s.player2 }}</div>
```

Replace with:

```html
{% if s.player1 or s.player2 %}
<div style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">
  {{ s.player1 }}{% if s.player1 and s.player2 %} &amp; {% endif %}{{ s.player2 }}
</div>
{% endif %}
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/templates/admin.html app/templates/partials/bracket.html
git commit -m "feat: guard optional player name display throughout templates"
```

---

### Task 6: Smoke test end-to-end

- [ ] **Step 1: Start app and create a tournament with 4 teams, no player names**

```
uvicorn app.main:app --reload
```

- Open `/setup`, add 4 teams (names only, no players)
- Start the tournament
- Confirm admin view shows 2 semifinal matches, no group tables, no player name errors

- [ ] **Step 2: Create a tournament with 6 teams, mixed player names**

Reset, then create 6 teams where some have players and some don't.
- Confirm group tables appear, player names show only where provided
- Confirm TV view `/tv` renders without errors

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: setup flow redesign complete"
```
