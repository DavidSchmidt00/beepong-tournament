# Dynamic Tournament Format

**Date:** 2026-04-29
**Status:** Approved

## Problem

The current tournament logic supports only one format: 2 groups + semifinals. With more than 8 teams the format becomes unbalanced (huge groups, only 4 KO slots). There is no quarterfinal round and no live feedback in the setup UI about how the tournament will look.

## Solution

Automatically select a tournament format based on team count. Add a live format preview to the setup page.

## Formats

| Teams | Groups | Advance | KO Rounds |
|-------|--------|---------|-----------|
| ≤4 | — | — | Semifinal → Final + 3rd place |
| 5–8 | 2 (A, B) | Top 2 per group | Semifinal → Final + 3rd place |
| 9–12 | 4 (A, B, C, D) | Top 2 per group | Quarterfinal → Semifinal → Final + 3rd place |

Maximum supported team count: 12.

## Quarterfinal Pairings (4 groups)

Cross-group seeding to avoid rematches from the group stage:

- QF1: A1 vs B2
- QF2: C1 vs D2
- QF3: B1 vs A2
- QF4: D1 vs C2

Winners of QF1/QF2 meet in SF1, winners of QF3/QF4 meet in SF2.

## Live Preview (Setup UI)

A preview box below the "+ Team hinzufügen" button updates on every team add/remove:

- **< 4 teams:** `⚠ Mindestens 4 Teams erforderlich`
- **≤ 4 teams:** `4 Teams → Halbfinale · Finale`
- **5–8 teams:** `6 Teams → 2 Gruppen (A, B) · Gruppenphase · Halbfinale · Finale`
- **9–12 teams:** `10 Teams → 4 Gruppen (A, B, C, D) · Gruppenphase · Viertelfinale · Halbfinale · Finale`

Implemented as a pure JS function `updateFormatPreview()` — no backend call needed. Logic mirrors the backend thresholds exactly.

## Backend Changes

### `app/models.py`
- `MatchRound` enum: add `quarterfinal`
- `Team.group`: change `String(1)` → `String(2)` to support "C" and "D" (SQLite ignores VARCHAR length, so no migration needed)

### `app/tournament.py`
- `split_into_four_groups(teams)`: splits shuffled list into 4 balanced groups (A, B, C, D)
- `generate_quarterfinals(standings_a, standings_b, standings_c, standings_d)`: returns 4 QF match specs using cross-group seeding above
- Existing `split_into_groups`, `get_ko_pairings` unchanged (still used for 5–8 teams)

### `app/main.py`
- `post_setup`: extend threshold logic
  - `num_teams <= 4` → direct KO (unchanged)
  - `5 <= num_teams <= 8` → 2 groups (unchanged)
  - `9 <= num_teams <= 12` → 4 groups via `split_into_four_groups()`
- Group-stage completion check: after all group matches done, if 4 groups exist, call `generate_quarterfinals()` instead of `get_ko_pairings()`
- QF completion check: when all 4 QF matches are done, generate the 2 SF matches from QF winners
- SF completion check: unchanged (already fills Final + 3rd place from SF winners)

### `app/templates/setup.html`
- Add format preview box (HTML + inline JS `updateFormatPreview()`)
- Call `updateFormatPreview()` from `addTeam()`, `removeTeam()`, and `updateStartButton()`

### `app/templates/` (bracket/admin/tv views)
- Render `quarterfinal` round where present — show QF column before SF in bracket view

## Out of Scope

- More than 12 teams
- Manual format selection by the user
- "Bye" slots / power-of-2 brackets
- Editable group assignments
