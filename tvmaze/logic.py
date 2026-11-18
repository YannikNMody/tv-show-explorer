"""Pure functions on TVmaze data: no network, no Streamlit, so they are easy to test."""
from __future__ import annotations

import html
import random
import re
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

# ---------------------------------------------------------------- formatting

_TAG = re.compile(r"<[^>]+>")


def strip_html(text: Optional[str]) -> str:
    """TVmaze summaries contain HTML (<p>, <b>); return plain text."""
    if not text:
        return ""
    return html.unescape(_TAG.sub("", text)).strip()


def episode_code(ep: dict) -> str:
    """S01E05, or 'S01 Special' for specials (they have no episode number)."""
    season, number = ep.get("season"), ep.get("number")
    if number is None:
        return f"S{season:02d} Special" if season is not None else "Special"
    return f"S{season:02d}E{number:02d}"


def rating_of(item: dict) -> Optional[float]:
    return (item.get("rating") or {}).get("average")


def format_minutes(minutes: float) -> str:
    hours, mins = divmod(int(round(minutes)), 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    return f"{hours} h" if hours else f"{mins} min"


def year_of(show: dict) -> str:
    return (show.get("premiered") or "")[:4] or "?"


def channel_of(show: dict) -> str:
    """Network (TV channel) or web channel (e.g. Netflix) name."""
    for key in ("network", "webChannel"):
        if show.get(key):
            return show[key]["name"]
    return "Unknown channel"


# ------------------------------------------------------------------ episodes

def group_by_season(episodes: Iterable[dict]) -> dict[int, list[dict]]:
    """{season number: [episodes in airing order]}, seasons ascending."""
    seasons: dict[int, list[dict]] = {}
    for ep in episodes:
        seasons.setdefault(ep.get("season") or 0, []).append(ep)
    return dict(sorted(seasons.items()))


def is_aired(ep: dict, today: date) -> bool:
    airdate = ep.get("airdate")
    return bool(airdate) and date.fromisoformat(airdate) <= today


# ------------------------------------------------------------------- heatmap

def rating_grid(episodes: Iterable[dict]) -> dict[int, dict[int, Optional[float]]]:
    """{season: {episode number: rating or None}}; specials are left out."""
    grid: dict[int, dict[int, Optional[float]]] = {}
    for ep in episodes:
        if ep.get("number") is None:
            continue
        grid.setdefault(ep["season"], {})[ep["number"]] = rating_of(ep)
    return dict(sorted(grid.items()))


def rating_summary(episodes: list[dict]) -> dict:
    """Share of rated episodes, best and worst episode, average per season."""
    regular = [e for e in episodes if e.get("number") is not None]
    rated = [e for e in regular if rating_of(e) is not None]
    season_avgs = {}
    for season, eps in group_by_season(rated).items():
        season_avgs[season] = round(sum(rating_of(e) for e in eps) / len(eps), 2)
    return {
        "share_rated": len(rated) / len(regular) if regular else 0.0,
        "best": max(rated, key=rating_of) if rated else None,
        "worst": min(rated, key=rating_of) if rated else None,
        "season_avgs": season_avgs,
    }


_RED, _YELLOW, _GREEN = (215, 48, 39), (254, 224, 139), (26, 152, 80)


def rating_color(value: Optional[float], low: float = 6.0, high: float = 9.5) -> str:
    """Hex colour from red (low) via yellow to green (high); grey when there is no rating."""
    if value is None or value != value:  # None or NaN
        return "#e0e0e0"
    t = min(max((value - low) / (high - low), 0.0), 1.0)
    start, end, u = (_RED, _YELLOW, t * 2) if t < 0.5 else (_YELLOW, _GREEN, (t - 0.5) * 2)
    return "#%02x%02x%02x" % tuple(round(start[i] + (end[i] - start[i]) * u) for i in range(3))


# ------------------------------------------------------------ binge planner

def episode_minutes(ep: dict, fallback: Optional[int]) -> int:
    return ep.get("runtime") or fallback or 0


def binge_plan(
    episodes: list[dict],
    minutes_per_day: int,
    weekdays: Iterable[int],
    start_date: date,
    fallback_runtime: Optional[int] = None,
) -> dict:
    """How long it takes to watch `episodes` at `minutes_per_day` on the given weekdays (0 = Monday).

    Returns episode count, total minutes, number of viewing days and the finish date.
    """
    weekdays = set(weekdays)
    if minutes_per_day <= 0:
        raise ValueError("Minutes per day must be more than 0.")
    if not weekdays:
        raise ValueError("Pick at least one viewing day.")

    total = sum(episode_minutes(e, fallback_runtime) for e in episodes)
    remaining, day, viewing_days = total, start_date, 0
    while remaining > 0:
        if day.weekday() in weekdays:
            viewing_days += 1
            remaining -= minutes_per_day
            if remaining <= 0:
                break
        day += timedelta(days=1)
    return {"episodes": len(episodes), "total_minutes": total, "viewing_days": viewing_days, "finish_date": day}


# --------------------------------------------------------------- crossover

def shared_cast(cast_a: list[dict], cast_b: list[dict]) -> list[dict]:
    """Actors in the main cast of both shows, with the character(s) they play in each."""

    def index(cast: list[dict]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for member in cast:
            person = member["person"]
            entry = out.setdefault(person["id"], {"name": person["name"], "characters": []})
            entry["characters"].append(member["character"]["name"])
        return out

    a, b = index(cast_a), index(cast_b)
    shared = [
        {
            "person_id": pid,
            "name": a[pid]["name"],
            "character_a": ", ".join(a[pid]["characters"]),
            "character_b": ", ".join(b[pid]["characters"]),
        }
        for pid in a
        if pid in b
    ]
    return sorted(shared, key=lambda row: row["name"])


# ------------------------------------------------------------- six degrees

def find_connection(
    start: tuple[int, str],
    goal: tuple[int, str],
    person_shows: Callable[[int], list[tuple[int, str]]],
    show_people: Callable[[int], list[tuple[int, str]]],
    max_expansions: int = 150,
    max_shows: int = 3,
    progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Shortest chain actor -> show -> actor -> ... between two people (bidirectional BFS).

    `start` and `goal` are (person id, name). Each expansion costs one API call, so the search
    stops after `max_expansions` and never links more than `max_shows` shows.
    Returns {"status": "found" | "no_path" | "too_far" | "budget", "path": [...] or None, "expansions": n}.
    """
    start_node, goal_node = ("person", start[0]), ("person", goal[0])
    names = {start_node: start[1], goal_node: goal[1]}
    if start_node == goal_node:
        return {"status": "found", "path": _labelled([start_node], names), "expansions": 0}

    parents = {"fwd": {start_node: None}, "bwd": {goal_node: None}}
    frontier = {"fwd": [start_node], "bwd": [goal_node]}
    depth = {"fwd": 0, "bwd": 0}
    max_edges = 2 * max_shows  # person -> show -> person is two edges per show
    expansions = 0

    def neighbours(node: tuple[str, int]) -> list[tuple[tuple[str, int], str]]:
        kind, node_id = node
        if kind == "person":
            return [(("show", sid), name) for sid, name in person_shows(node_id)]
        return [(("person", pid), name) for pid, name in show_people(node_id)]

    while frontier["fwd"] and frontier["bwd"]:
        if depth["fwd"] + depth["bwd"] + 1 > max_edges:
            return {"status": "too_far", "path": None, "expansions": expansions}
        # grow the smaller side; on a tie, the shallower one (so a dead end is noticed quickly)
        side = min(("fwd", "bwd"), key=lambda s: (len(frontier[s]), depth[s]))
        other = "bwd" if side == "fwd" else "fwd"
        next_frontier = []
        for node in frontier[side]:
            if expansions >= max_expansions:
                return {"status": "budget", "path": None, "expansions": expansions}
            expansions += 1
            if progress:
                progress(expansions, max_expansions)
            for neighbour, name in neighbours(node):
                names.setdefault(neighbour, name)
                if neighbour in parents[side]:
                    continue
                parents[side][neighbour] = node
                if neighbour in parents[other]:
                    return {"status": "found", "path": _build_path(neighbour, parents, names), "expansions": expansions}
                next_frontier.append(neighbour)
        frontier[side] = next_frontier
        depth[side] += 1
    return {"status": "no_path", "path": None, "expansions": expansions}


def _build_path(meeting, parents, names) -> list[dict]:
    path, node = [], meeting
    while node is not None:
        path.append(node)
        node = parents["fwd"][node]
    path.reverse()
    node = parents["bwd"][meeting]
    while node is not None:
        path.append(node)
        node = parents["bwd"][node]
    return _labelled(path, names)


def _labelled(nodes, names) -> list[dict]:
    return [{"kind": kind, "id": node_id, "name": names.get((kind, node_id), "?")} for kind, node_id in nodes]


# -------------------------------------------------------- higher or lower

def game_pool(shows: Iterable[dict], min_weight: int = 80) -> list[dict]:
    """Shows that have a rating and are popular enough (TVmaze 'weight') to be recognisable."""
    return [s for s in shows if rating_of(s) is not None and (s.get("weight") or 0) >= min_weight]


def pick_pair(pool: list[dict], rng: random.Random, seen: Iterable[int] = ()) -> tuple[dict, dict]:
    """Two different shows, preferring ones not used yet in this game."""
    if len(pool) < 2:
        raise ValueError("Need at least two shows to play.")
    seen = set(seen)
    fresh = [s for s in pool if s["id"] not in seen]
    candidates = fresh if len(fresh) >= 2 else pool
    a, b = rng.sample(candidates, 2)
    return a, b


def is_correct_guess(choice: str, rating_a: float, rating_b: float) -> bool:
    """`choice` is "a" or "b" (the one guessed to be rated higher). A tie counts as correct."""
    if rating_a == rating_b:
        return True
    return (choice == "a") == (rating_a > rating_b)
