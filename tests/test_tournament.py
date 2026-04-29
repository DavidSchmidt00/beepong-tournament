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
    teams = [make_team(1, "T1", "A"), make_team(2, "T2", "A"), make_team(3, "T3", "A")]
    matches = [
        # T1 beats T2, 5 cups to 0
        make_match(1, 1, 2, "A", MatchStatus.completed, winner_id=1, cups_a=5, cups_b=0),
        # T2 beats T3, 1 cup to 0
        make_match(2, 2, 3, "A", MatchStatus.completed, winner_id=2, cups_a=1, cups_b=0),
        # T3 beats T1, 1 cup to 0
        make_match(3, 3, 1, "A", MatchStatus.completed, winner_id=3, cups_a=1, cups_b=0),
    ]
    # T1: 1 win, cups_scored=5+0=5, cups_conceded=0+1=1 → diff=4
    # T2: 1 win, cups_scored=0+1=1, cups_conceded=5+0=5 → diff=-4
    # T3: 1 win, cups_scored=0+1=1, cups_conceded=0+1=1 → diff=0
    # Ordering: T1 (diff=4) > T3 (diff=0) > T2 (diff=-4)
    standings = calculate_standings(teams, matches)
    assert standings[0]["team_id"] == 1
    assert standings[1]["team_id"] == 3
    assert standings[2]["team_id"] == 2


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
