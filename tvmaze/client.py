"""TVmaze API client.

Every request to TVmaze goes through this one class, so caching, throttling,
retries and error handling live in a single place.

TVmaze facts this is built around (https://www.tvmaze.com/api):
- no API key, read-only (GET only), JSON responses
- rate limit: at least 20 calls per 10 seconds per IP, then HTTP 429
- responses are cached on their side for 60 minutes anyway
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Iterable, Optional

import requests

BASE_URL = "https://api.tvmaze.com"
USER_AGENT = "tv-show-explorer/1.0 (student project)"


class ApiError(Exception):
    """Something went wrong talking to TVmaze (network, server, unexpected status)."""


class NotFoundError(ApiError):
    """TVmaze answered 404: the show, person or page does not exist."""


class RateLimitError(ApiError):
    """TVmaze kept answering 429 (too many requests), even after retrying."""


class TVMazeClient:
    """Small wrapper around the TVmaze REST API.

    - Cache: identical requests within `cache_ttl` seconds are answered from memory.
    - Throttle: at most `max_calls` network calls per `period` seconds (TVmaze allows 20 / 10 s).
    - Retry: on HTTP 429, wait `retry_delays` seconds in turn, then give up.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        cache_ttl: float = 3600,
        max_calls: int = 18,
        period: float = 10.0,
        retry_delays: Iterable[float] = (2, 4, 8),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cache_ttl = cache_ttl
        self.max_calls = max_calls
        self.period = period
        self.retry_delays = tuple(retry_delays)
        self._clock = clock
        self._sleep = sleep
        self._cache: dict[str, tuple[float, Any]] = {}
        self._recent_calls: deque[float] = deque()
        self.network_calls = 0  # how many real HTTP requests were made (cache hits not counted)

    # ------------------------------------------------------------------ core

    def get(self, path: str, params: Optional[dict] = None, ttl: Optional[float] = None) -> Any:
        """GET `path` (e.g. "/shows/1") and return the parsed JSON, using the cache when possible."""
        params = params or {}
        key = f"{path}?{sorted(params.items())}"
        now = self._clock()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        data = self._fetch(path, params)
        self._cache[key] = (now + (ttl if ttl is not None else self.cache_ttl), data)
        return data

    def _throttle(self) -> None:
        """Wait if we already made `max_calls` calls in the last `period` seconds."""
        now = self._clock()
        while self._recent_calls and now - self._recent_calls[0] >= self.period:
            self._recent_calls.popleft()
        if len(self._recent_calls) >= self.max_calls:
            wait = self.period - (now - self._recent_calls[0])
            if wait > 0:
                self._sleep(wait)
            self._recent_calls.popleft()
        self._recent_calls.append(self._clock())

    def _fetch(self, path: str, params: dict) -> Any:
        url = BASE_URL + path
        for attempt in range(len(self.retry_delays) + 1):
            self._throttle()
            self.network_calls += 1
            try:
                response = self.session.get(url, params=params, timeout=15)
            except requests.RequestException as exc:
                raise ApiError(f"Could not reach TVmaze ({exc.__class__.__name__}). Check your internet connection.") from exc

            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                raise NotFoundError(f"TVmaze has nothing at {path}.")
            if response.status_code == 429:
                if attempt < len(self.retry_delays):
                    self._sleep(self.retry_delays[attempt])
                    continue
                raise RateLimitError("TVmaze's rate limit was reached. Wait a few seconds and try again.")
            raise ApiError(f"TVmaze returned HTTP {response.status_code} for {path}.")
        raise ApiError("Unreachable")  # pragma: no cover

    # ------------------------------------------------------------- endpoints

    def search_shows(self, query: str) -> list[dict]:
        """GET /search/shows?q= : fuzzy search, best match first."""
        return [hit["show"] for hit in self.get("/search/shows", {"q": query})]

    def get_show(self, show_id: int, embed: Iterable[str] = ()) -> dict:
        """GET /shows/:id, optionally with embedded resources (e.g. ["nextepisode"])."""
        embed = list(embed)
        params = {"embed[]": embed} if embed else {}
        return self.get(f"/shows/{show_id}", params)

    def get_episodes(self, show_id: int, specials: bool = False) -> list[dict]:
        """GET /shows/:id/episodes : every episode in airing order (specials only if asked)."""
        params = {"specials": 1} if specials else {}
        return self.get(f"/shows/{show_id}/episodes", params)

    def get_cast(self, show_id: int) -> list[dict]:
        """GET /shows/:id/cast : main cast, each item has a person and a character."""
        return self.get(f"/shows/{show_id}/cast")

    def search_people(self, query: str) -> list[dict]:
        """GET /search/people?q= : fuzzy search for actors and crew."""
        return [hit["person"] for hit in self.get("/search/people", {"q": query})]

    def get_cast_credits(self, person_id: int) -> list[dict]:
        """GET /people/:id/castcredits?embed=show : the shows a person was main cast in."""
        return self.get(f"/people/{person_id}/castcredits", {"embed": "show"})

    def get_shows_page(self, page: int) -> list[dict]:
        """GET /shows?page=N : the full show index, 250 IDs per page (cached for 24 h)."""
        return self.get("/shows", {"page": page}, ttl=24 * 3600)

    # ------------------------------------------ graph helpers for six degrees

    def person_shows(self, person_id: int) -> list[tuple[int, str]]:
        """(show id, show name) for every show the person was main cast in."""
        seen: dict[int, str] = {}
        for credit in self.get_cast_credits(person_id):
            show = credit.get("_embedded", {}).get("show")
            if show:
                seen.setdefault(show["id"], show["name"])
        return list(seen.items())

    def show_people(self, show_id: int) -> list[tuple[int, str]]:
        """(person id, name) for every main cast member of a show."""
        seen: dict[int, str] = {}
        for member in self.get_cast(show_id):
            seen.setdefault(member["person"]["id"], member["person"]["name"])
        return list(seen.items())
