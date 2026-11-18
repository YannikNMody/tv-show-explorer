import json

import pytest

from tvmaze import tracker


def test_missing_or_corrupt_file_gives_empty_tracker(tmp_path):
    assert tracker.load(tmp_path / "nope.json") == tracker.empty()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert tracker.load(bad) == tracker.empty()


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "tracker.json"
    data = tracker.empty()
    tracker.follow(data, {"id": 1, "name": "Girls"})
    tracker.set_watched(data, 1, [11, 12], True)
    tracker.save(data, path)
    assert tracker.load(path) == data


def test_follow_watch_unfollow():
    data = tracker.empty()
    tracker.follow(data, {"id": 1, "name": "Girls"})
    assert tracker.is_followed(data, 1)
    tracker.set_watched(data, 1, [3, 1, 2], True)
    tracker.set_watched(data, 1, [2], False)
    assert tracker.watched_ids(data, 1) == {1, 3}
    tracker.unfollow(data, 1)
    assert not tracker.is_followed(data, 1)
    assert tracker.watched_ids(data, 1) == set()


def test_next_unwatched_and_progress():
    episodes = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert tracker.next_unwatched(episodes, {1})["id"] == 2
    assert tracker.next_unwatched(episodes, {1, 2, 3}) is None
    assert tracker.progress(episodes, {1, 3, 99}) == (2, 3)


def test_validate_rejects_foreign_files_and_fills_settings():
    with pytest.raises(ValueError):
        tracker.validate({"hello": "world"})
    data = tracker.validate(json.loads('{"version": 1, "shows": {}}'))
    assert data["settings"] == {"spoiler_free": False, "game_best": 0}
