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


def generate_direct_ko_bracket(teams: list[dict]) -> list[dict]:
    """Generate KO matches directly for 4 teams (no group stage). Teams must be pre-shuffled."""
    return [
        {"team_a_id": teams[0]["id"], "team_b_id": teams[1]["id"], "round": MatchRound.semifinal, "group": None, "status": MatchStatus.pending},
        {"team_a_id": teams[2]["id"], "team_b_id": teams[3]["id"], "round": MatchRound.semifinal, "group": None, "status": MatchStatus.pending},
        {"team_a_id": None, "team_b_id": None, "round": MatchRound.final, "group": None, "status": MatchStatus.pending},
        {"team_a_id": None, "team_b_id": None, "round": MatchRound.third_place, "group": None, "status": MatchStatus.pending},
    ]


def get_ko_pairings(standings_a: list[dict], standings_b: list[dict]) -> list[dict]:
    """
    Generate KO matches from top-2 of each group.
    SF1: A1 vs B2, SF2: B1 vs A2.
    Final and 3rd place have no team IDs yet (filled after semis complete).
    """
    a1, a2 = standings_a[0].get("team_id") or standings_a[0]["id"], standings_a[1].get("team_id") or standings_a[1]["id"]
    b1, b2 = standings_b[0].get("team_id") or standings_b[0]["id"], standings_b[1].get("team_id") or standings_b[1]["id"]
    return [
        {"team_a_id": a1, "team_b_id": b2, "round": MatchRound.semifinal, "group": None, "status": MatchStatus.pending},
        {"team_a_id": b1, "team_b_id": a2, "round": MatchRound.semifinal, "group": None, "status": MatchStatus.pending},
        {"team_a_id": None, "team_b_id": None, "round": MatchRound.final, "group": None, "status": MatchStatus.pending},
        {"team_a_id": None, "team_b_id": None, "round": MatchRound.third_place, "group": None, "status": MatchStatus.pending},
    ]


def get_next_matches(matches: list[dict]) -> list[dict]:
    """Return all currently pending matches."""
    return [m for m in matches if m["status"] == MatchStatus.pending]
