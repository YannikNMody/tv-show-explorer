"""Smoke tests for the Streamlit app: every page renders against a fake TVmaze, without internet."""
import pytest
from streamlit.testing.v1 import AppTest

SHOW = {
    "id": 1, "name": "Demo Show", "url": "https://www.tvmaze.com/shows/1", "premiered": "2020-01-01",
    "ended": None, "status": "Running", "language": "English", "genres": ["Drama"],
    "rating": {"average": 8.1}, "weight": 99, "network": {"name": "HBO"}, "webChannel": None,
    "image": None, "summary": "<p>A <b>demo</b>.</p>", "averageRuntime": 30,
}
EPISODES = [
    {"id": 11, "season": 1, "number": 1, "name": "Pilot", "airdate": "2020-01-01", "runtime": 30,
     "rating": {"average": 7.5}, "summary": "<p>Start.</p>"},
    {"id": 12, "season": 1, "number": 2, "name": "Second", "airdate": "2020-01-08", "runtime": 30,
     "rating": {"average": 8.5}, "summary": "<p>More.</p>"},
    {"id": 13, "season": 1, "number": None, "name": "Special", "airdate": "2020-02-01", "runtime": 30,
     "rating": {"average": None}, "summary": None},
]


class FakeClient:
    network_calls = 0

    def search_shows(self, q):
        return [SHOW, {**SHOW, "id": 2, "name": "Other Show"}]

    def get_show(self, show_id, embed=()):
        return {**SHOW, "id": show_id}

    def get_episodes(self, show_id, specials=False):
        return EPISODES if specials else [e for e in EPISODES if e["number"] is not None]

    def get_cast(self, show_id):
        return [{"person": {"id": 5, "name": "Ann Actor"}, "character": {"name": "Hero"}}]

    def search_people(self, q):
        return [{"id": 5, "name": "Ann Actor", "birthday": "1980-01-01", "country": {"name": "UK"}}]

    def person_shows(self, person_id):
        return [(1, "Demo Show")]

    def show_people(self, show_id):
        return [(5, "Ann Actor")]

    def get_shows_page(self, page):
        return [SHOW, {**SHOW, "id": 2, "name": "Other Show", "rating": {"average": 6.0}}]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_PATH", str(tmp_path / "tracker.json"))
    monkeypatch.setattr("tvmaze.client.TVMazeClient", lambda *a, **k: FakeClient())
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.run()
    assert not at.exception
    return at


def go(at, page):
    at.sidebar.radio(key="page").set_value(page).run()
    assert not at.exception


def test_search_open_show_and_list_all_episodes(app):
    app.text_input(key="query").input("demo").run()
    assert "Demo Show" in app.markdown[0].value or any("Demo Show" in m.value for m in app.markdown)
    app.button(key="open_1").click().run()
    assert not app.exception
    assert any("S01E01 · Pilot" in m.value for m in app.markdown)
    app.checkbox(key="specials_1").check().run()
    assert any("S01 Special" in m.value for m in app.markdown)


def test_follow_and_tick_episode(app):
    app.text_input(key="query").input("demo").run()
    app.button(key="open_1").click().run()
    follow = next(b for b in app.button if "Follow" in b.label)
    follow.click().run()
    assert not app.exception
    app.checkbox(key="w_1_11").check().run()
    assert not app.exception
    go(app, "My shows")
    assert any("Up next" in m.value and "Second" in m.value for m in app.markdown)


def test_other_pages_render(app):
    for page in ("My shows", "Cast crossover", "Six degrees", "Higher or lower", "About"):
        go(app, page)


def test_six_degrees_finds_same_show(app):
    go(app, "Six degrees")
    app.text_input(key="pa_q").input("ann").run()
    app.text_input(key="pb_q").input("ann").run()
    app.button[0].click().run()
    assert not app.exception
    assert any("Connected" in s.value for s in app.success)
