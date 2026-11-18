import random
from datetime import date

import pytest

from tvmaze import logic


def ep(id, season, number, rating=None, runtime=30, airdate="2020-01-01"):
    return {"id": id, "season": season, "number": number, "name": f"Ep {id}",
            "rating": {"average": rating}, "runtime": runtime, "airdate": airdate}


# ---------------------------------------------------------------- formatting

def test_strip_html():
    assert logic.strip_html("<p>Tom &amp; <b>Jerry</b></p>") == "Tom & Jerry"
    assert logic.strip_html(None) == ""


def test_episode_code_regular_and_special():
    assert logic.episode_code(ep(1, 2, 5)) == "S02E05"
    assert logic.episode_code(ep(1, 2, None)) == "S02 Special"


def test_format_minutes():
    assert logic.format_minutes(45) == "45 min"
    assert logic.format_minutes(120) == "2 h"
    assert logic.format_minutes(135) == "2 h 15 min"


def test_channel_of_prefers_network_then_web_channel():
    assert logic.channel_of({"network": {"name": "HBO"}, "webChannel": None}) == "HBO"
    assert logic.channel_of({"network": None, "webChannel": {"name": "Netflix"}}) == "Netflix"


# ------------------------------------------------------------------ episodes

def test_group_by_season_keeps_order():
    eps = [ep(3, 2, 1), ep(1, 1, 1), ep(2, 1, 2)]
    grouped = logic.group_by_season(eps)
    assert list(grouped) == [1, 2]
    assert [e["id"] for e in grouped[1]] == [1, 2]


def test_is_aired():
    today = date(2026, 1, 1)
    assert logic.is_aired(ep(1, 1, 1, airdate="2025-12-31"), today)
    assert not logic.is_aired(ep(1, 1, 1, airdate="2026-02-01"), today)
    assert not logic.is_aired(ep(1, 1, 1, airdate=""), today)


# ------------------------------------------------------------------- heatmap

def test_rating_grid_skips_specials():
    grid = logic.rating_grid([ep(1, 1, 1, 8.0), ep(2, 1, None, 9.0), ep(3, 2, 1, None)])
    assert grid == {1: {1: 8.0}, 2: {1: None}}


def test_rating_summary():
    eps = [ep(1, 1, 1, 7.0), ep(2, 1, 2, 9.0), ep(3, 2, 1, None), ep(4, 2, 2, 8.0)]
    summary = logic.rating_summary(eps)
    assert summary["share_rated"] == 0.75
    assert summary["best"]["id"] == 2 and summary["worst"]["id"] == 1
    assert summary["season_avgs"] == {1: 8.0, 2: 8.0}


def test_rating_color():
    assert logic.rating_color(None) == "#e0e0e0"
    assert logic.rating_color(float("nan")) == "#e0e0e0"
    assert logic.rating_color(3.0) == "#d73027"   # clamped to red
    assert logic.rating_color(10.0) == "#1a9850"  # clamped to green


# ------------------------------------------------------------ binge planner

def test_binge_plan_every_day():
    # 4 x 30 min at 60 min/day = 2 days, finishing the day after the start
    plan = logic.binge_plan([ep(i, 1, i) for i in range(1, 5)], 60, range(7), date(2026, 1, 5))
    assert plan == {"episodes": 4, "total_minutes": 120, "viewing_days": 2, "finish_date": date(2026, 1, 6)}


def test_binge_plan_weekends_only():
    # Monday start, Sat+Sun only, 3 viewing days needed -> Sat, Sun, next Sat
    plan = logic.binge_plan([ep(i, 1, i) for i in range(1, 4)], 30, [5, 6], date(2026, 1, 5))
    assert plan["viewing_days"] == 3
    assert plan["finish_date"] == date(2026, 1, 17)


def test_binge_plan_uses_fallback_runtime():
    plan = logic.binge_plan([ep(1, 1, 1, runtime=None)], 60, range(7), date(2026, 1, 5), fallback_runtime=45)
    assert plan["total_minutes"] == 45


def test_binge_plan_validates_input():
    with pytest.raises(ValueError):
        logic.binge_plan([ep(1, 1, 1)], 0, range(7), date(2026, 1, 5))
    with pytest.raises(ValueError):
        logic.binge_plan([ep(1, 1, 1)], 60, [], date(2026, 1, 5))


# --------------------------------------------------------------- crossover

def member(pid, name, character):
    return {"person": {"id": pid, "name": name}, "character": {"name": character}}


def test_shared_cast():
    a = [member(1, "Zoe", "Ann"), member(2, "Bob", "Ben"), member(2, "Bob", "Ben's twin")]
    b = [member(2, "Bob", "Carl"), member(3, "Cy", "Dee")]
    assert logic.shared_cast(a, b) == [
        {"person_id": 2, "name": "Bob", "image": None, "character_a": "Ben, Ben's twin", "character_b": "Carl"}
    ]
    assert logic.shared_cast(a, [member(3, "Cy", "Dee")]) == []


# ------------------------------------------------------------- six degrees

# Small fake TV world:  A -[S1]- B -[S2]- C -[S3]- D -[S4]- E ;  Z is in nothing
SHOWS = {1: ["A", "B"], 2: ["B", "C"], 3: ["C", "D"], 4: ["D", "E"]}
PEOPLE = {p: i for i, p in enumerate("ABCDEZ", start=100)}


def person_shows(pid):
    name = next(n for n, i in PEOPLE.items() if i == pid)
    return [(sid, f"Show {sid}") for sid, cast in SHOWS.items() if name in cast]


def show_people(sid):
    return [(PEOPLE[n], n) for n in SHOWS[sid]]


def connect(a, b, **kwargs):
    return logic.find_connection((PEOPLE[a], a), (PEOPLE[b], b), person_shows, show_people, **kwargs)


def test_direct_co_stars():
    result = connect("A", "B")
    assert result["status"] == "found"
    assert [n["name"] for n in result["path"]] == ["A", "Show 1", "B"]


def test_three_show_chain():
    result = connect("A", "D")
    assert [n["name"] for n in result["path"]] == ["A", "Show 1", "B", "Show 2", "C", "Show 3", "D"]


def test_too_far_for_max_shows():
    assert connect("A", "E", max_shows=3)["status"] == "too_far"
    assert connect("A", "E", max_shows=4)["status"] == "found"


def test_no_path_and_same_person():
    assert connect("A", "Z")["status"] == "no_path"
    assert connect("A", "A")["path"] == [{"kind": "person", "id": PEOPLE["A"], "name": "A"}]


def test_budget_stops_search():
    result = connect("A", "D", max_expansions=2)
    assert result["status"] == "budget"
    assert result["expansions"] == 2


def test_progress_callback_called():
    calls = []
    connect("A", "C", progress=lambda done, limit: calls.append(done))
    assert calls and calls == sorted(calls)


# -------------------------------------------------------- higher or lower

def test_game_pool_filters_unrated_and_obscure():
    shows = [{"id": 1, "rating": {"average": 8}, "weight": 95},
             {"id": 2, "rating": {"average": None}, "weight": 99},
             {"id": 3, "rating": {"average": 7}, "weight": 10}]
    assert [s["id"] for s in logic.game_pool(shows)] == [1]


def test_pick_pair_prefers_unseen_and_is_distinct():
    pool = [{"id": i} for i in range(4)]
    a, b = logic.pick_pair(pool, random.Random(1), seen={0, 1})
    assert {a["id"], b["id"]} == {2, 3}
    with pytest.raises(ValueError):
        logic.pick_pair(pool[:1], random.Random(1))


def test_is_correct_guess():
    assert logic.is_correct_guess("a", 8.5, 7.0)
    assert not logic.is_correct_guess("b", 8.5, 7.0)
    assert logic.is_correct_guess("b", 7.0, 7.0)  # tie counts as correct
