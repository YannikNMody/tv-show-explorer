"""Watch tracker: which shows you follow and which episodes you watched.

TVmaze's public API is read-only and has no user accounts, so this data is ours.
It is stored in a local JSON file (data/tracker.json by default, or $TRACKER_PATH).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

VERSION = 1


def default_path() -> Path:
    return Path(os.environ.get("TRACKER_PATH", Path(__file__).resolve().parent.parent / "data" / "tracker.json"))


def empty() -> dict:
    return {"version": VERSION, "shows": {}, "settings": {"spoiler_free": False, "game_best": 0}}


def load(path: Optional[Path] = None) -> dict:
    """Read the tracker file; a missing or unreadable file gives an empty tracker."""
    path = Path(path or default_path())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty()
    return validate(data)


def validate(data: dict) -> dict:
    """Check the shape (used for loading and for imported files); fill in missing settings."""
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("shows"), dict):
        raise ValueError("This is not a tracker file from this app (version 1).")
    data.setdefault("settings", {})
    for key, value in empty()["settings"].items():
        data["settings"].setdefault(key, value)
    return data


def save(data: dict, path: Optional[Path] = None) -> None:
    """Write atomically: a crash mid-write cannot leave a half-written file."""
    path = Path(path or default_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def is_followed(data: dict, show_id: int) -> bool:
    return str(show_id) in data["shows"]


def follow(data: dict, show: dict) -> None:
    data["shows"].setdefault(str(show["id"]), {"name": show["name"], "watched": []})


def unfollow(data: dict, show_id: int) -> None:
    data["shows"].pop(str(show_id), None)


def watched_ids(data: dict, show_id: int) -> set[int]:
    entry = data["shows"].get(str(show_id))
    return set(entry["watched"]) if entry else set()


def set_watched(data: dict, show_id: int, episode_ids: Iterable[int], watched: bool) -> None:
    """Mark one or more episodes of a followed show as watched (or not)."""
    entry = data["shows"][str(show_id)]
    current = set(entry["watched"])
    current = current | set(episode_ids) if watched else current - set(episode_ids)
    entry["watched"] = sorted(current)


def next_unwatched(episodes: list[dict], watched: set[int]) -> Optional[dict]:
    """First episode, in airing order, that is not watched yet."""
    return next((ep for ep in episodes if ep["id"] not in watched), None)


def progress(episodes: list[dict], watched: set[int]) -> tuple[int, int]:
    """(watched, total) counted over the given episodes."""
    return sum(ep["id"] in watched for ep in episodes), len(episodes)
