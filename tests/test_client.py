"""Client tests: no internet needed, a fake session plays TVmaze."""
import pytest
import requests

from tvmaze.client import ApiError, NotFoundError, RateLimitError, TVMazeClient


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    """Time that only moves when the client sleeps, so tests run instantly."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(*responses, **kwargs):
    clock = FakeClock()
    session = FakeSession(*responses)
    client = TVMazeClient(session=session, clock=clock, sleep=clock.sleep, **kwargs)
    return client, session, clock


def test_get_returns_json_and_sets_user_agent():
    client, session, _ = make_client(FakeResponse(200, {"id": 1}))
    assert client.get("/shows/1") == {"id": 1}
    assert session.calls[0][0] == "https://api.tvmaze.com/shows/1"
    assert "tv-show-explorer" in session.headers["User-Agent"]


def test_second_identical_request_comes_from_cache():
    client, session, _ = make_client(FakeResponse(200, {"id": 1}))
    client.get("/shows/1")
    client.get("/shows/1")
    assert len(session.calls) == 1
    assert client.network_calls == 1


def test_cache_expires_after_ttl():
    client, session, clock = make_client(FakeResponse(200, {"v": 1}), FakeResponse(200, {"v": 2}), cache_ttl=60)
    assert client.get("/shows/1") == {"v": 1}
    clock.now += 61
    assert client.get("/shows/1") == {"v": 2}
    assert len(session.calls) == 2


def test_404_raises_not_found():
    client, _, _ = make_client(FakeResponse(404))
    with pytest.raises(NotFoundError):
        client.get("/shows/999999999")


def test_429_is_retried_with_backoff():
    client, session, clock = make_client(FakeResponse(429), FakeResponse(429), FakeResponse(200, []))
    assert client.get("/search/shows", {"q": "x"}) == []
    assert len(session.calls) == 3
    assert clock.sleeps == [2, 4]


def test_429_gives_up_after_all_retries():
    client, session, _ = make_client(*[FakeResponse(429)] * 4)
    with pytest.raises(RateLimitError):
        client.get("/shows/1")
    assert len(session.calls) == 4


def test_network_error_becomes_api_error():
    client, _, _ = make_client(requests.ConnectionError("offline"))
    with pytest.raises(ApiError, match="Could not reach TVmaze"):
        client.get("/shows/1")


def test_server_error_becomes_api_error():
    client, _, _ = make_client(FakeResponse(500))
    with pytest.raises(ApiError, match="HTTP 500"):
        client.get("/shows/1")


def test_throttle_waits_when_limit_reached():
    client, _, clock = make_client(*[FakeResponse(200, {})] * 3, max_calls=2, period=10)
    client.get("/a")
    client.get("/b")
    assert clock.sleeps == []
    client.get("/c")
    assert clock.sleeps == [10]


def test_search_shows_unwraps_results():
    client, session, _ = make_client(FakeResponse(200, [{"score": 0.9, "show": {"id": 1, "name": "Girls"}}]))
    assert client.search_shows("girls") == [{"id": 1, "name": "Girls"}]
    assert session.calls[0][1] == {"q": "girls"}


def test_get_show_with_embeds_and_episodes_with_specials():
    client, session, _ = make_client(FakeResponse(200, {"id": 1}), FakeResponse(200, []))
    client.get_show(1, embed=["nextepisode", "cast"])
    client.get_episodes(1, specials=True)
    assert session.calls[0][1] == {"embed[]": ["nextepisode", "cast"]}
    assert session.calls[1] == ("https://api.tvmaze.com/shows/1/episodes", {"specials": 1})


def test_graph_helpers_deduplicate():
    credits = [
        {"_embedded": {"show": {"id": 5, "name": "A"}}},
        {"_embedded": {"show": {"id": 5, "name": "A"}}},
        {"_embedded": {"show": {"id": 6, "name": "B"}}},
    ]
    cast = [
        {"person": {"id": 1, "name": "X"}, "character": {"name": "c1"}},
        {"person": {"id": 1, "name": "X"}, "character": {"name": "c2"}},
    ]
    client, _, _ = make_client(FakeResponse(200, credits), FakeResponse(200, cast))
    assert client.person_shows(9) == [(5, "A"), (6, "B")]
    assert client.show_people(5) == [(1, "X")]
