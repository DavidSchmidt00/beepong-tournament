# Setup Flow Redesign

**Date:** 2026-04-29  
**Status:** Approved

## Problem

The current setup form has two pain points on mobile:
1. The user must pre-select the number of teams before seeing any team fields.
2. All team fields are rendered at once, resulting in a long scrolling form.

## Solution

Replace the static form with a dynamic team-adding flow.

## Design

### Layout

**Top section (static)**
- Tournament name input
- Admin password input

**Team list (dynamic)**
- Each card contains: emoji picker + team name *(required)* + player 1 *(optional)* + player 2 *(optional)* + delete button
- Cards are stacked vertically, added one at a time

**Footer**
- Prominent "+ Team hinzufügen" button
- "Turnier starten 🚀" button — disabled/hidden until at least 4 teams are entered

### Behaviour

- The page starts with one empty team card.
- Tapping "+ Team hinzufügen" appends a new empty card and scrolls to it.
- Any card can be deleted (with a minimum of 1 card always remaining).
- The start button activates once ≥ 4 teams have a team name filled in.
- On submit, the number of teams is derived from the submitted form data — no `num_players` dropdown.

### Player names

Both player 1 and player 2 are optional on every team card. A team can have zero, one, or two named players.

## Backend Changes

- `post_setup`: read `num_teams` from the count of submitted team entries, not from a `num_players` field.
- `Tournament.num_players`: can be removed or kept as a derived value (`num_teams * 2`) for display purposes — not used for logic.
- `Team.player1`: change to `nullable=True`.
- `Team.player2`: already changed to `nullable=True`.
- All template display of player names guards against `None` (e.g. `{% if t.player1 %}...{% endif %}`).

## Files to Change

| File | Change |
|------|--------|
| `app/templates/setup.html` | Full rewrite of form — dynamic JS team cards, no num_players select |
| `app/main.py` | `get_setup`: remove `num_players_options`. `post_setup`: derive num_teams from form keys |
| `app/models.py` | `player1` → nullable |
| `app/templates/admin.html` | Guard player name display |
| `app/templates/partials/bracket.html` | Guard player name display |

## Out of Scope

- Teams joining themselves via QR code
- Editing teams after the tournament has started
