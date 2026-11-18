"""TV Show Explorer: a Streamlit app on top of the TVmaze API.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
import random
from datetime import date

import pandas as pd
import streamlit as st

from tvmaze import logic, tracker
from tvmaze.client import ApiError, NotFoundError, TVMazeClient

st.set_page_config(page_title="TV Show Explorer", page_icon="📺", layout="wide")

PAGES = ["Search & episodes", "My shows", "Cast crossover", "Six degrees", "Higher or lower", "About"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@st.cache_resource
def get_client() -> TVMazeClient:
    """One client for the whole app, so its cache and rate limiter are shared."""
    return TVMazeClient()


client = get_client()
if "tracker" not in st.session_state:
    st.session_state.tracker = tracker.load()
data = st.session_state.tracker


# ------------------------------------------------------------------ helpers

def save_tracker() -> None:
    tracker.save(st.session_state.tracker)


def api(fn, *args, **kwargs):
    """Call the API and turn errors into a message on the page instead of a crash."""
    try:
        return fn(*args, **kwargs)
    except NotFoundError:
        st.warning("TVmaze has no data for this.")
    except ApiError as exc:
        st.error(str(exc))
    return None


def open_show(show_id: int) -> None:
    st.session_state.show_id = show_id
    st.session_state.page = PAGES[0]


def close_show() -> None:
    st.session_state.show_id = None


def toggle_follow(show: dict) -> None:
    if tracker.is_followed(data, show["id"]):
        tracker.unfollow(data, show["id"])
    else:
        tracker.follow(data, show)
    save_tracker()


def toggle_watched(show_id: int, episode_id: int) -> None:
    checked = st.session_state[f"w_{show_id}_{episode_id}"]
    tracker.set_watched(data, show_id, [episode_id], checked)
    save_tracker()


def mark_season(show_id: int, episode_ids: list[int], watched: bool) -> None:
    tracker.set_watched(data, show_id, episode_ids, watched)
    for episode_id in episode_ids:
        st.session_state[f"w_{show_id}_{episode_id}"] = watched
    save_tracker()


def show_line(show: dict) -> str:
    genres = ", ".join(show.get("genres") or []) or "no genre"
    rating = logic.rating_of(show)
    return (
        f"**{show['name']}** ({logic.year_of(show)}) · {logic.channel_of(show)} · {genres} · "
        f"★ {rating if rating is not None else '–'} · {show.get('status', '')}"
    )


def show_picker(label: str, key: str) -> dict | None:
    """Search box + dropdown to choose one show."""
    query = st.text_input(label, key=f"{key}_q")
    if not query:
        return None
    results = api(client.search_shows, query)
    if not results:
        if results == []:
            st.warning(f"No shows found for “{query}”.")
        return None
    return st.selectbox(
        "Pick the right one", results, key=f"{key}_sel",
        format_func=lambda s: f"{s['name']} ({logic.year_of(s)}, {logic.channel_of(s)})",
    )


def person_picker(label: str, key: str) -> dict | None:
    """Search box + dropdown to choose one person."""
    query = st.text_input(label, key=f"{key}_q")
    if not query:
        return None
    results = api(client.search_people, query)
    if not results:
        if results == []:
            st.warning(f"No people found for “{query}”.")
        return None
    return st.selectbox(
        "Pick the right one", results, key=f"{key}_sel",
        format_func=lambda p: f"{p['name']} ({(p.get('birthday') or '?')[:4]}, {(p.get('country') or {}).get('name', '?')})",
    )


# ------------------------------------------------------- search & show page

def page_search() -> None:
    st.title("📺 TV Show Explorer")
    query = st.text_input("Search for a show", key="query", placeholder="e.g. Severance", on_change=close_show)

    if st.session_state.get("show_id"):
        st.button("← Back to results", on_click=close_show)
        render_show(st.session_state.show_id)
        return

    if not query:
        st.info("Type a show name to start. Typos are fine: TVmaze uses fuzzy search.")
        return
    results = api(client.search_shows, query)
    if results is None:
        return
    if not results:
        st.warning(f"No shows found for “{query}”.")
        return
    st.caption(f"{len(results)} results, best match first")
    for show in results:
        cols = st.columns([1, 6, 1])
        image = (show.get("image") or {}).get("medium")
        if image:
            cols[0].image(image, width=70)
        cols[1].markdown(show_line(show))
        cols[2].button("Open", key=f"open_{show['id']}", on_click=open_show, args=(show["id"],))


def render_show(show_id: int) -> None:
    show = api(client.get_show, show_id, embed=["nextepisode"])
    if not show:
        return
    followed = tracker.is_followed(data, show_id)

    left, right = st.columns([1, 4])
    image = (show.get("image") or {}).get("medium")
    if image:
        left.image(image)
    with right:
        st.header(show["name"])
        st.markdown(show_line(show))
        ended = show.get("ended") or ("now" if show.get("status") == "Running" else "?")
        st.caption(f"Aired {show.get('premiered') or '?'} to {ended} · {show.get('language') or ''} · "
                   f"[TVmaze page]({show['url']})")
        st.write(logic.strip_html(show.get("summary")))
        nxt = show.get("_embedded", {}).get("nextepisode")
        if nxt:
            st.info(f"Next new episode: {logic.episode_code(nxt)} “{nxt['name']}” on {nxt.get('airdate') or 'TBA'}")
        st.button("★ Unfollow" if followed else "☆ Follow (track what you watch)",
                  on_click=toggle_follow, args=(show,))

    tab_eps, tab_heat, tab_binge, tab_cast = st.tabs(["All episodes", "Rating heatmap", "Binge plan", "Cast"])
    with tab_eps:
        render_episodes(show, followed)
    with tab_heat:
        render_heatmap(show)
    with tab_binge:
        render_binge(show, followed)
    with tab_cast:
        render_cast(show)


def render_episodes(show: dict, followed: bool) -> None:
    show_id = show["id"]
    specials = st.checkbox("Include specials", key=f"specials_{show_id}")
    episodes = api(client.get_episodes, show_id, specials=specials)
    if episodes is None:
        return
    if not episodes:
        st.info("TVmaze lists no episodes for this show yet.")
        return

    watched = tracker.watched_ids(data, show_id) if followed else set()
    spoiler_free = followed and data["settings"]["spoiler_free"]
    position = {ep["id"]: i for i, ep in enumerate(episodes)}
    upcoming = tracker.next_unwatched(episodes, watched) if followed else None
    hide_after = position[upcoming["id"]] if (spoiler_free and upcoming) else None

    seasons = logic.group_by_season(episodes)
    st.caption(f"{len(episodes)} episodes in {len(seasons)} seasons"
               + (" · spoiler-free mode is on" if spoiler_free else ""))
    if not followed:
        st.caption("Follow the show to tick off episodes you have watched.")

    for season, eps in seasons.items():
        done = sum(ep["id"] in watched for ep in eps)
        label = f"Season {season} · {len(eps)} episodes" + (f" · {done}/{len(eps)} watched" if followed else "")
        with st.expander(label, expanded=len(seasons) == 1):
            if followed:
                ids = [ep["id"] for ep in eps]
                b1, b2, _ = st.columns([1, 1, 4])
                b1.button("Mark season watched", key=f"sw_{show_id}_{season}", on_click=mark_season, args=(show_id, ids, True))
                b2.button("Mark season unwatched", key=f"su_{show_id}_{season}", on_click=mark_season, args=(show_id, ids, False))
            for ep in eps:
                rating = logic.rating_of(ep)
                line = (f"**{logic.episode_code(ep)} · {ep['name']}** · {ep.get('airdate') or 'TBA'} · "
                        f"{ep.get('runtime') or '?'} min · ★ {rating if rating is not None else '–'}")
                if followed:
                    key = f"w_{show_id}_{ep['id']}"
                    if key not in st.session_state:
                        st.session_state[key] = ep["id"] in watched
                    st.checkbox(line, key=key, on_change=toggle_watched, args=(show_id, ep["id"]))
                else:
                    st.markdown(line)
                summary = logic.strip_html(ep.get("summary"))
                hidden = hide_after is not None and position[ep["id"]] > hide_after and ep["id"] not in watched
                if summary and hidden:
                    st.caption("Summary hidden (spoiler-free mode)")
                elif summary:
                    st.caption(summary)


def render_heatmap(show: dict) -> None:
    episodes = api(client.get_episodes, show["id"])
    if not episodes:
        st.info("No episodes to show.")
        return
    grid = logic.rating_grid(episodes)
    summary = logic.rating_summary(episodes)
    if summary["share_rated"] == 0:
        st.info("None of the episodes has a rating on TVmaze yet.")
        return
    if summary["share_rated"] < 0.5:
        st.warning(f"Only {summary['share_rated']:.0%} of episodes have a rating, so the grid has gaps.")

    max_episode = max(max(eps) for eps in grid.values())
    frame = pd.DataFrame(
        [[grid[s].get(n) for n in range(1, max_episode + 1)] for s in grid],
        index=[f"Season {s}" for s in grid],
        columns=[f"E{n}" for n in range(1, max_episode + 1)],
        dtype="float",
    )
    styled = frame.style.map(lambda v: f"background-color: {logic.rating_color(v)}; color: #111").format("{:.1f}", na_rep="")
    st.caption("Each cell is one episode, coloured from red (weak) to green (great). Grey = no rating.")
    st.dataframe(styled, use_container_width=True)

    best, worst = summary["best"], summary["worst"]
    c1, c2 = st.columns(2)
    c1.success(f"Best: {logic.episode_code(best)} “{best['name']}” ★ {logic.rating_of(best)}")
    c2.error(f"Weakest: {logic.episode_code(worst)} “{worst['name']}” ★ {logic.rating_of(worst)}")
    st.subheader("Average rating per season")
    st.bar_chart(pd.Series({f"S{s}": avg for s, avg in summary["season_avgs"].items()}, name="rating"))


def render_binge(show: dict, followed: bool) -> None:
    episodes = api(client.get_episodes, show["id"])
    if not episodes:
        st.info("No episodes to plan.")
        return
    today = date.today()
    aired = [ep for ep in episodes if logic.is_aired(ep, today)]
    not_aired = len(episodes) - len(aired)
    if not aired:
        st.info("No episode has aired yet.")
        return

    options = ["From the first episode", "From an episode I choose"]
    if followed:
        options.insert(1, "From my next unwatched episode")
    start_mode = st.radio("Start", options, horizontal=True, key=f"bstart_{show['id']}")
    if start_mode == "From my next unwatched episode":
        upcoming = tracker.next_unwatched(aired, tracker.watched_ids(data, show["id"]))
        if upcoming is None:
            st.success("You have watched every aired episode.")
            return
        start_index = aired.index(upcoming)
    elif start_mode == "From an episode I choose":
        chosen = st.selectbox("First episode", aired, key=f"bep_{show['id']}",
                              format_func=lambda ep: f"{logic.episode_code(ep)} · {ep['name']}")
        start_index = aired.index(chosen)
    else:
        start_index = 0

    c1, c2, c3 = st.columns(3)
    minutes = c1.number_input("Minutes per day", min_value=10, max_value=1440, value=90, step=15, key=f"bmin_{show['id']}")
    days = c2.multiselect("Viewing days", WEEKDAYS, default=WEEKDAYS, key=f"bdays_{show['id']}")
    start_date = c3.date_input("Start date", value=today, key=f"bdate_{show['id']}")
    try:
        plan = logic.binge_plan(aired[start_index:], int(minutes), [WEEKDAYS.index(d) for d in days], start_date,
                                fallback_runtime=show.get("averageRuntime") or show.get("runtime"))
    except ValueError as exc:
        st.warning(str(exc))
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Episodes", plan["episodes"])
    m2.metric("Total watch time", logic.format_minutes(plan["total_minutes"]))
    m3.metric("Viewing days", plan["viewing_days"])
    m4.metric("You finish on", plan["finish_date"].strftime("%a %d %b %Y"))
    if not_aired:
        st.caption(f"{not_aired} announced episode(s) that have not aired yet are not counted.")


def render_cast(show: dict) -> None:
    cast = api(client.get_cast, show["id"])
    if not cast:
        st.info("TVmaze lists no cast for this show.")
        return
    st.dataframe(
        pd.DataFrame([{"Actor": m["person"]["name"], "Character": m["character"]["name"]} for m in cast]),
        hide_index=True, use_container_width=True,
    )


# ----------------------------------------------------------------- my shows

def page_my_shows() -> None:
    st.title("My shows")
    key = "spoiler_toggle"
    if key not in st.session_state:
        st.session_state[key] = data["settings"]["spoiler_free"]

    def on_spoiler_change() -> None:
        data["settings"]["spoiler_free"] = st.session_state[key]
        save_tracker()

    st.toggle("Spoiler-free mode (hide summaries of episodes you have not reached)", key=key, on_change=on_spoiler_change)

    if not data["shows"]:
        st.info("You follow no shows yet. Open a show and press Follow.")
    today = date.today()
    for show_id_str, entry in list(data["shows"].items()):
        show_id = int(show_id_str)
        show = api(client.get_show, show_id, embed=["nextepisode"])
        episodes = api(client.get_episodes, show_id)
        if show is None or episodes is None:
            continue
        aired = [ep for ep in episodes if logic.is_aired(ep, today)]
        watched = set(entry["watched"])
        done, total = tracker.progress(aired, watched)
        with st.container(border=True):
            cols = st.columns([1, 5, 1])
            image = (show.get("image") or {}).get("medium")
            if image:
                cols[0].image(image, width=80)
            with cols[1]:
                st.subheader(show["name"])
                st.progress(done / total if total else 0.0, text=f"{done} of {total} aired episodes watched")
                upcoming = tracker.next_unwatched(aired, watched)
                st.write(f"Up next: **{logic.episode_code(upcoming)} · {upcoming['name']}**" if upcoming
                         else "You are up to date.")
                nxt = show.get("_embedded", {}).get("nextepisode")
                if nxt:
                    st.caption(f"Next new episode airs {nxt.get('airdate') or 'TBA'}: {logic.episode_code(nxt)} “{nxt['name']}”")
            cols[2].button("Open", key=f"my_open_{show_id}", on_click=open_show, args=(show_id,))

    st.divider()
    st.subheader("Backup")
    st.download_button("Export tracker (JSON)", json.dumps(data, indent=2), file_name="tracker.json", mime="application/json")
    upload = st.file_uploader("Import a tracker file", type="json")
    if upload is not None and st.button("Replace my tracker with this file"):
        try:
            st.session_state.tracker = tracker.validate(json.loads(upload.read()))
        except (ValueError, json.JSONDecodeError) as exc:
            st.error(f"Could not import: {exc}")
        else:
            save_tracker()
            st.success("Imported.")
            st.rerun()


# ---------------------------------------------------------------- crossover

def page_crossover() -> None:
    st.title("Cast crossover")
    st.caption("Pick two shows and see which actors were in the main cast of both.")
    c1, c2 = st.columns(2)
    with c1:
        show_a = show_picker("First show", "xa")
    with c2:
        show_b = show_picker("Second show", "xb")
    if not (show_a and show_b):
        return
    if show_a["id"] == show_b["id"]:
        st.warning("Pick two different shows.")
        return
    cast_a, cast_b = api(client.get_cast, show_a["id"]), api(client.get_cast, show_b["id"])
    if cast_a is None or cast_b is None:
        return
    shared = logic.shared_cast(cast_a, cast_b)
    if not shared:
        st.info(f"No shared main cast between {show_a['name']} and {show_b['name']}.")
    else:
        st.success(f"{len(shared)} actor(s) in both shows")
        st.dataframe(pd.DataFrame([
            {"Actor": row["name"], f"In {show_a['name']}": row["character_a"], f"In {show_b['name']}": row["character_b"]}
            for row in shared
        ]), hide_index=True, use_container_width=True)
    st.caption("Main cast only: guest roles would need one API call per episode.")


# -------------------------------------------------------------- six degrees

def page_six_degrees() -> None:
    st.title("Six degrees of TV")
    st.caption("Connect two actors through shows they were in the main cast of: actor → show → actor → …")
    c1, c2 = st.columns(2)
    with c1:
        person_a = person_picker("First actor", "pa")
    with c2:
        person_b = person_picker("Second actor", "pb")
    c3, c4 = st.columns(2)
    max_shows = c3.slider("Maximum shows in the chain", 1, 3, 3)
    budget = c4.slider("Maximum API calls", 20, 300, 150, step=10,
                       help="Each step costs one call; TVmaze allows about 20 calls per 10 seconds.")
    if not (person_a and person_b):
        return
    if st.button("Find connection", type="primary"):
        bar = st.progress(0.0, text="Searching…")
        result = api(
            logic.find_connection,
            (person_a["id"], person_a["name"]), (person_b["id"], person_b["name"]),
            person_shows=client.person_shows, show_people=client.show_people,
            max_expansions=budget, max_shows=max_shows,
            progress=lambda done, limit: bar.progress(min(done / limit, 1.0), text=f"{done} lookups so far…"),
        )
        bar.empty()
        st.session_state.six_result = result

    result = st.session_state.get("six_result")
    if not result:
        return
    status = result["status"]
    if status == "found":
        shows = sum(node["kind"] == "show" for node in result["path"])
        st.success(f"Connected through {shows} show(s) after {result['expansions']} lookups")
        parts = [f"**{n['name']}**" if n["kind"] == "person" else f"📺 *{n['name']}*" for n in result["path"]]
        st.markdown(" → ".join(parts))
    elif status == "budget":
        st.warning(f"No connection found within {result['expansions']} lookups. Raise the API call limit and try again.")
    elif status == "too_far":
        st.warning("These two are not connected within the maximum number of shows.")
    else:
        st.info("No connection exists through main-cast roles.")


# ------------------------------------------------------------ higher/lower

def new_round() -> None:
    game = st.session_state.game
    game["pair"] = logic.pick_pair(game["pool"], game["rng"], game["seen"])
    game["seen"].update(s["id"] for s in game["pair"])
    game["answer"] = None


def guess(choice: str) -> None:
    game = st.session_state.game
    a, b = game["pair"]
    correct = logic.is_correct_guess(choice, logic.rating_of(a), logic.rating_of(b))
    game["answer"] = correct
    if correct:
        game["score"] += 1
        if game["score"] > data["settings"]["game_best"]:
            data["settings"]["game_best"] = game["score"]
            save_tracker()


def restart() -> None:
    st.session_state.game["score"] = 0
    st.session_state.game["seen"] = set()
    new_round()


def page_game() -> None:
    st.title("Higher or lower")
    st.caption("Which show has the higher TVmaze rating? One wrong guess ends your streak.")
    if "game" not in st.session_state:
        shows = []
        for page in (0, 1, 2):
            shows += api(client.get_shows_page, page) or []
        pool = logic.game_pool(shows) or logic.game_pool(shows, min_weight=0)
        if len(pool) < 2:
            st.error("Could not load enough shows to play.")
            return
        st.session_state.game = {"pool": pool, "rng": random.Random(), "seen": set(), "score": 0, "pair": None, "answer": None}
        new_round()

    game = st.session_state.game
    s1, s2 = st.columns(2)
    s1.metric("Streak", game["score"])
    s2.metric("Best ever", data["settings"]["game_best"])

    cols = st.columns(2)
    for col, show, choice in zip(cols, game["pair"], ("a", "b")):
        with col, st.container(border=True):
            st.subheader(show["name"])
            st.caption(f"{logic.year_of(show)} · {logic.channel_of(show)} · {', '.join(show.get('genres') or [])}")
            image = (show.get("image") or {}).get("medium")
            if image:
                st.image(image, width=160)
            if game["answer"] is None:
                st.button("This one is rated higher", key=f"guess_{choice}", on_click=guess, args=(choice,))
            else:
                st.metric("Rating", logic.rating_of(show))

    if game["answer"] is True:
        st.success("Correct!")
        st.button("Next round", on_click=new_round, type="primary")
    elif game["answer"] is False:
        st.error(f"Wrong. Your streak was {game['score']}.")
        st.button("Play again", on_click=restart, type="primary")


# -------------------------------------------------------------------- about

def page_about() -> None:
    st.title("About")
    st.markdown(
        """
TV Show Explorer is built on the free [TVmaze API](https://www.tvmaze.com/api).
Every request goes through one client (`tvmaze/client.py`) that caches responses for an hour,
keeps to 18 calls per 10 seconds and retries when TVmaze answers *429 Too Many Requests*.

| Feature | TVmaze endpoints |
|---|---|
| Search, show page | `/search/shows`, `/shows/:id?embed[]=nextepisode` |
| All episodes, heatmap, binge plan | `/shows/:id/episodes` (`?specials=1` for specials) |
| Cast, crossover | `/shows/:id/cast` |
| Six degrees | `/search/people`, `/people/:id/castcredits?embed=show`, `/shows/:id/cast` |
| Higher or lower | `/shows?page=N` |

Your followed shows and watched episodes are stored locally in `data/tracker.json`.

Data: [TVmaze](https://www.tvmaze.com), licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
"""
    )
    st.caption(f"Network calls made by this app since it started: {client.network_calls}")


# ---------------------------------------------------------------- navigation

st.sidebar.title("TV Show Explorer")
page = st.sidebar.radio("Go to", PAGES, key="page")
st.sidebar.caption("Data from [TVmaze](https://www.tvmaze.com) (CC BY-SA 4.0)")

{
    PAGES[0]: page_search,
    PAGES[1]: page_my_shows,
    PAGES[2]: page_crossover,
    PAGES[3]: page_six_degrees,
    PAGES[4]: page_game,
    PAGES[5]: page_about,
}[page]()
