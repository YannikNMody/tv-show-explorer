"""TV Show Explorer: a Streamlit app on top of the TVmaze API.

Run with:  streamlit run app.py
Design: Apple-inspired (see style.css and .streamlit/config.toml).
"""
from __future__ import annotations

import html
import json
import random
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from tvmaze import logic, tracker
from tvmaze.client import ApiError, NotFoundError, TVMazeClient

st.set_page_config(page_title="TV Show Explorer", page_icon="📺", layout="wide", initial_sidebar_state="collapsed")

HERE = Path(__file__).parent
PAGES = ["Search", "My shows", "Crossover", "Six degrees", "Higher or lower", "About"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ACCENT = "#0071e3"
FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Helvetica Neue', Arial, sans-serif"


@st.cache_resource
def get_client() -> TVMazeClient:
    """One client for the whole app, so its cache and rate limiter are shared."""
    return TVMazeClient()


client = get_client()
if "tracker" not in st.session_state:
    st.session_state.tracker = tracker.load()
data = st.session_state.tracker


# ====================================================================== helpers

def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def img_url(item: dict | None) -> str:
    """Medium image URL from a TVmaze show/person/episode, only if it is https."""
    url = ((item or {}).get("image") or {}).get("medium") or ""
    return esc(url) if url.startswith("https://") else ""


def poster_html(item: dict | None, round_: bool = False, fallback: str = "📺") -> str:
    url = img_url(item)
    inner = f'<img src="{url}" alt="" loading="lazy">' if url else fallback
    return f'<div class="poster{" round" if round_ else ""}">{inner}</div>'


def rating_html(value) -> str:
    return f'<span class="rating"><span class="star">★</span> {value:.1f}</span>' if value is not None \
        else '<span class="rating muted">No rating</span>'


def pills(*items: str, kind: str = "") -> str:
    return "".join(f'<span class="pill {kind}">{esc(i)}</span>' for i in items if i)


def html_block(markup: str, target=None) -> None:
    (target or st).markdown(markup, unsafe_allow_html=True)


def panel(key: str, title: str, subtitle: str = ""):
    box = st.container(key=f"panel-{key}")
    sub = f'<p class="panel-sub">{esc(subtitle)}</p>' if subtitle else ""
    html_block(f'<p class="panel-title">{esc(title)}</p>{sub}', box)
    return box


def kpis(tiles: list[tuple[str, str, str]]) -> None:
    html_block('<div class="kpis">' + "".join(
        f'<div class="kpi"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div>'
        f'<div class="note">{esc(note)}</div></div>' for label, value, note in tiles) + "</div>")


def spacer(size: str = "medium") -> None:
    """Vertical breathing room (works on every Streamlit version)."""
    height = {"small": 8, "medium": 20, "large": 40}[size]
    html_block(f'<div style="height:{height}px"></div>')


def empty_state(text: str) -> None:
    html_block(f'<p class="muted center" style="padding:2.5rem 0">{esc(text)}</p>')


def style_chart(chart: alt.Chart, height: int = 240) -> alt.Chart:
    return (chart.properties(height=height, background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelFont=FONT, titleFont=FONT, labelColor="#6e6e73", titleColor="#6e6e73",
                            labelFontSize=12, titleFontSize=12, gridColor="#ececf0", domain=False, tickColor="#ececf0"))


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


# ---------------------------------------------------------------- callbacks

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
    tracker.set_watched(data, show_id, [episode_id], st.session_state[f"w_{show_id}_{episode_id}"])
    save_tracker()


def mark_season(show_id: int, episode_ids: list[int], watched: bool) -> None:
    tracker.set_watched(data, show_id, episode_ids, watched)
    for episode_id in episode_ids:
        st.session_state[f"w_{show_id}_{episode_id}"] = watched
    save_tracker()


# ------------------------------------------------------------------ pickers

def show_picker(label: str, key: str) -> dict | None:
    query = st.text_input(label, key=f"{key}_q", placeholder="Search a show")
    if not query:
        return None
    results = api(client.search_shows, query)
    if not results:
        if results == []:
            st.warning(f"No shows found for “{query}”.")
        return None
    return st.selectbox("Pick the right one", results, key=f"{key}_sel", label_visibility="collapsed",
                        format_func=lambda s: f"{s['name']} ({logic.year_of(s)}, {logic.channel_of(s)})")


def person_picker(label: str, key: str) -> dict | None:
    query = st.text_input(label, key=f"{key}_q", placeholder="Search an actor")
    if not query:
        return None
    results = api(client.search_people, query)
    if not results:
        if results == []:
            st.warning(f"No people found for “{query}”.")
        return None
    return st.selectbox("Pick the right one", results, key=f"{key}_sel", label_visibility="collapsed",
                        format_func=lambda p: f"{p['name']} ({(p.get('birthday') or '?')[:4]}, "
                                              f"{(p.get('country') or {}).get('name', '?')})")


def show_card(container, show: dict, key_prefix: str, width: int = 196) -> None:
    card = container.container(key=f"card-{key_prefix}-{show['id']}", width=width)
    html_block(
        poster_html(show)
        + f'<div class="card-eyebrow">{esc(logic.channel_of(show))} · {esc(logic.year_of(show))}</div>'
        + f'<div class="card-title" title="{esc(show["name"])}">{esc(show["name"])}</div>'
        + f'<div class="card-meta">{rating_html(logic.rating_of(show))}'
        + f'{pills(show.get("status"), kind="green" if show.get("status") == "Running" else "")}</div>', card)
    card.button("Open", key=f"open_{show['id']}" if key_prefix == "res" else f"{key_prefix}_open_{show['id']}",
                on_click=open_show, args=(show["id"],), type="tertiary")


# ================================================================ search page

def page_search() -> None:
    if st.session_state.get("show_id"):
        st.button("← Back to results", on_click=close_show, type="tertiary")
        render_show(st.session_state.show_id)
        return

    html_block('<div class="hero"><p class="eyebrow">Powered by TVmaze</p>'
               '<h1>Every show. Every episode.</h1>'
               '<p class="sub">Search any TV show, see all of its episodes, and find out which ones are worth '
               'your evening.</p></div>')
    box = st.container(key="searchbox")
    query = box.text_input("Search for a show", key="query", placeholder="Search a show, e.g. Severance",
                           on_change=close_show, label_visibility="collapsed")
    if not query:
        empty_state("Typos are fine: TVmaze uses fuzzy search.")
        return
    results = api(client.search_shows, query)
    if results is None:
        return
    if not results:
        empty_state(f"No shows found for “{query}”.")
        return
    html_block(f'<p class="muted" style="margin:0 0 1rem">{len(results)} results, best match first</p>')
    grid = st.container(horizontal=True, gap="medium", key="results")
    for show in results:
        show_card(grid, show, "res")


def render_show(show_id: int) -> None:
    show = api(client.get_show, show_id, embed=["nextepisode"])
    if not show:
        return
    episodes = api(client.get_episodes, show_id) or []
    followed = tracker.is_followed(data, show_id)

    left, right = st.columns([1, 3.2], gap="large")
    url = img_url(show)
    html_block(f'<div class="show-poster"><img src="{url}" alt=""></div>' if url else poster_html(None), left)
    with right:
        ended = show.get("ended") or ("today" if show.get("status") == "Running" else "?")
        html_block(
            f'<div class="show-eyebrow">{esc(logic.channel_of(show))} · {esc((show.get("premiered") or "?")[:4])}'
            f'–{esc(ended[:4] if ended != "today" else "today")}</div>'
            f'<div class="show-title">{esc(show["name"])}</div>'
            f'<div>{rating_html(logic.rating_of(show))} &nbsp; '
            f'{pills(show.get("status"), kind="green" if show.get("status") == "Running" else "")}'
            f'{pills(*(show.get("genres") or []), kind="blue")}{pills(show.get("language"))}</div>'
            f'<p class="show-summary">{esc(logic.strip_html(show.get("summary")))}</p>')
        nxt = show.get("_embedded", {}).get("nextepisode")
        if nxt:
            html_block(f'<div class="next-up">Next new episode: <b>{esc(logic.episode_code(nxt))} '
                       f'“{esc(nxt["name"])}”</b> on {esc(nxt.get("airdate") or "TBA")}</div>')
        b1, b2 = st.columns([1.3, 1])
        b1.button("✓ Following" if followed else "+ Follow this show", on_click=toggle_follow, args=(show,),
                  type="secondary" if followed else "primary", width="stretch")
        b2.link_button("Open on TVmaze", show["url"], width="stretch")

    spacer("medium")
    seasons = logic.group_by_season(episodes)
    summary = logic.rating_summary(episodes)
    avg = [r for r in summary["season_avgs"].values()]
    total = sum(logic.episode_minutes(e, show.get("averageRuntime")) for e in episodes)
    kpis([
        ("Seasons", str(len(seasons)), f"{len(episodes)} episodes"),
        ("Total runtime", logic.format_minutes(total) if total else "–", "to watch it all"),
        ("Average episode", f"★ {sum(avg) / len(avg):.1f}" if avg else "–",
         f"{summary['share_rated']:.0%} of episodes rated" if episodes else ""),
        ("Your progress", f"{len(tracker.watched_ids(data, show_id) & {e['id'] for e in episodes})}/{len(episodes)}"
         if followed else "–", "episodes watched" if followed else "follow to track"),
    ])

    tab_eps, tab_heat, tab_binge, tab_cast = st.tabs(["All episodes", "Rating heatmap", "Binge plan", "Cast"])
    with tab_eps:
        render_episodes(show, followed)
    with tab_heat:
        render_heatmap(episodes)
    with tab_binge:
        render_binge(show, episodes, followed)
    with tab_cast:
        render_cast(show)


def episode_html(ep: dict, hidden: bool, watched: bool) -> str:
    rating = logic.rating_of(ep)
    meta = f'{esc(ep.get("airdate") or "TBA")} · {esc(ep.get("runtime") or "?")} min' + \
           (f' · <span class="star" style="color:var(--star)">★</span> {rating:.1f}' if rating is not None else "")
    summary = logic.strip_html(ep.get("summary"))
    if hidden and summary:
        sum_html = '<div class="ep-sum hidden">Summary hidden (spoiler-free mode)</div>'
    else:
        sum_html = f'<div class="ep-sum">{esc(summary)}</div>' if summary else ""
    return (f'<div class="ep{" watched" if watched else ""}"><div class="ep-code">{esc(logic.episode_code(ep))}</div>'
            f'<div class="ep-name">{esc(ep["name"])}</div><div class="ep-meta">{meta}</div>{sum_html}</div>')


def render_episodes(show: dict, followed: bool) -> None:
    show_id = show["id"]
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    specials = c2.toggle("Include specials", key=f"specials_{show_id}")
    episodes = api(client.get_episodes, show_id, specials=specials)
    if episodes is None:
        return
    if not episodes:
        empty_state("TVmaze lists no episodes for this show yet.")
        return

    watched = tracker.watched_ids(data, show_id) if followed else set()
    spoiler_free = followed and data["settings"]["spoiler_free"]
    position = {ep["id"]: i for i, ep in enumerate(episodes)}
    upcoming = tracker.next_unwatched(episodes, watched) if followed else None
    hide_after = position[upcoming["id"]] if (spoiler_free and upcoming) else None
    seasons = logic.group_by_season(episodes)
    note = " · spoiler-free mode is on" if spoiler_free else ("" if followed else " · follow the show to tick off episodes")
    html_block(f'<p class="muted">{len(episodes)} episodes in {len(seasons)} seasons{esc(note)}</p>', c1)

    for season, eps in seasons.items():
        done = sum(ep["id"] in watched for ep in eps)
        label = f"Season {season}  ·  {len(eps)} episodes" + (f"  ·  {done}/{len(eps)} watched" if followed else "")
        with st.expander(label, expanded=len(seasons) == 1):
            if not followed:
                html_block("".join(episode_html(ep, False, False) for ep in eps))
                continue
            ids = [ep["id"] for ep in eps]
            b1, b2, _ = st.columns([1, 1, 3])
            b1.button("Mark season watched", key=f"sw_{show_id}_{season}", on_click=mark_season,
                      args=(show_id, ids, True), type="tertiary")
            b2.button("Mark season unwatched", key=f"su_{show_id}_{season}", on_click=mark_season,
                      args=(show_id, ids, False), type="tertiary")
            for ep in eps:
                key = f"w_{show_id}_{ep['id']}"
                if key not in st.session_state:
                    st.session_state[key] = ep["id"] in watched
                hidden = hide_after is not None and position[ep["id"]] > hide_after and ep["id"] not in watched
                row = st.container(key=f"eprow-{show_id}-{ep['id']}")
                box, body = row.columns([0.35, 10], gap="small")
                box.checkbox("Watched", key=key, on_change=toggle_watched, args=(show_id, ep["id"]),
                             label_visibility="collapsed")
                html_block(episode_html(ep, hidden, ep["id"] in watched), body)


def render_heatmap(episodes: list[dict]) -> None:
    if not episodes:
        empty_state("No episodes to show.")
        return
    grid = logic.rating_grid(episodes)
    summary = logic.rating_summary(episodes)
    if summary["share_rated"] == 0:
        empty_state("None of the episodes has a rating on TVmaze yet.")
        return
    names = {(e["season"], e["number"]): e["name"] for e in episodes if e.get("number") is not None}
    max_episode = max(max(eps) for eps in grid.values())

    rows = ['<div class="heat-row heat-head"><div class="heat-label"></div>'
            + "".join(f'<div class="heat-cell">{n}</div>' for n in range(1, max_episode + 1)) + "</div>"]
    for season, eps in grid.items():
        cells = []
        for n in range(1, max_episode + 1):
            if n not in eps:
                cells.append('<div class="heat-cell empty"></div>')
                continue
            value = eps[n]
            tip = f'S{season:02d}E{n:02d} · {names.get((season, n), "")} · {value if value is not None else "no rating"}'
            cells.append(f'<div class="heat-cell" style="background:{logic.rating_color(value)}" title="{esc(tip)}">'
                         f'{"" if value is None else f"{value:.1f}"}</div>')
        rows.append(f'<div class="heat-row"><div class="heat-label">S{season}</div>{"".join(cells)}</div>')

    with panel("heatmap", "Episode ratings", "One cell per episode. Hover a cell for its title."):
        if summary["share_rated"] < 0.5:
            st.caption(f"Only {summary['share_rated']:.0%} of episodes have a rating, so the grid has gaps.")
        html_block(f'<div class="heat">{"".join(rows)}</div>'
                   '<div class="legend">6.0 <span class="bar"></span> 9.5 <span class="none"></span> no rating</div>')

    best, worst = summary["best"], summary["worst"]
    spacer("small")
    kpis([
        ("Best episode", f"★ {logic.rating_of(best):.1f}", f"{logic.episode_code(best)} · {best['name']}"),
        ("Weakest episode", f"★ {logic.rating_of(worst):.1f}", f"{logic.episode_code(worst)} · {worst['name']}"),
    ])
    if len(summary["season_avgs"]) > 1:
        frame = pd.DataFrame({"Season": [f"S{s}" for s in summary["season_avgs"]],
                              "Rating": list(summary["season_avgs"].values())})
        low = max(min(frame["Rating"]) - 0.5, 0)
        chart = alt.Chart(frame).mark_bar(cornerRadiusEnd=6, color=ACCENT).encode(
            x=alt.X("Season:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Rating:Q", title=None, scale=alt.Scale(domain=[low, 10])),
            tooltip=["Season", alt.Tooltip("Rating:Q", format=".2f")])
        with panel("seasons", "Average rating per season"):
            st.altair_chart(style_chart(chart), use_container_width=True, theme=None)


def render_binge(show: dict, episodes: list[dict], followed: bool) -> None:
    today = date.today()
    aired = [ep for ep in episodes if logic.is_aired(ep, today)]
    if not aired:
        empty_state("No episode has aired yet.")
        return

    with panel("binge", "Plan your binge", "When will you be done if you watch a little every day?"):
        options = ["From the first episode", "From an episode I choose"]
        if followed:
            options.insert(1, "From my next unwatched episode")
        start_mode = st.radio("Start", options, horizontal=True, key=f"bstart_{show['id']}",
                              label_visibility="collapsed")
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
        c1, c2, c3 = st.columns([1, 1.6, 1])
        minutes = c1.number_input("Minutes per day", min_value=10, max_value=1440, value=90, step=15,
                                  key=f"bmin_{show['id']}")
        days = c2.pills("Viewing days", WEEKDAYS, selection_mode="multi", default=WEEKDAYS,
                        key=f"bdays_{show['id']}") or []
        start_date = c3.date_input("Start date", value=today, key=f"bdate_{show['id']}")
    try:
        plan = logic.binge_plan(aired[start_index:], int(minutes), [WEEKDAYS.index(d) for d in days], start_date,
                                fallback_runtime=show.get("averageRuntime") or show.get("runtime"))
    except ValueError as exc:
        st.warning(str(exc))
        return
    spacer("small")
    kpis([
        ("You finish on", f'{plan["finish_date"].day} {plan["finish_date"]:%b %Y}', f'{plan["finish_date"]:%A}'),
        ("Episodes", str(plan["episodes"]), f"from {logic.episode_code(aired[start_index])}"),
        ("Total watch time", logic.format_minutes(plan["total_minutes"]), "without breaks"),
        ("Viewing days", str(plan["viewing_days"]), f"{int(minutes)} min each"),
    ])
    not_aired = len(episodes) - len(aired)
    if not_aired:
        st.caption(f"{not_aired} announced episode(s) that have not aired yet are not counted.")


def person_card(container, key: str, person: dict, lines: list[str]) -> None:
    card = container.container(key=f"card-{key}", width=176)
    html_block(poster_html(person, round_=True, fallback="👤")
               + f'<div class="card-title center">{esc(person["name"])}</div>'
               + "".join(f'<div class="card-sub center">{line}</div>' for line in lines), card)


def render_cast(show: dict) -> None:
    cast = api(client.get_cast, show["id"])
    if not cast:
        empty_state("TVmaze lists no cast for this show.")
        return
    grid = st.container(horizontal=True, gap="medium", key="castgrid")
    for i, member in enumerate(cast):
        person_card(grid, f"cast-{i}", member["person"], [f'as {esc(member["character"]["name"])}'])


# =================================================================== my shows

def page_my_shows() -> None:
    html_block('<div class="hero"><p class="eyebrow">My shows</p><h1>Pick up where you left off.</h1>'
               '<p class="sub">Shows you follow, what you have watched, and what airs next.</p></div>')
    key = "spoiler_toggle"
    if key not in st.session_state:
        st.session_state[key] = data["settings"]["spoiler_free"]

    def on_spoiler_change() -> None:
        data["settings"]["spoiler_free"] = st.session_state[key]
        save_tracker()

    _, mid, _ = st.columns([1, 2, 1])
    mid.toggle("Spoiler-free mode: hide summaries of episodes I have not reached", key=key, on_change=on_spoiler_change)
    spacer("small")

    if not data["shows"]:
        empty_state("You follow no shows yet. Open a show and press “Follow this show”.")
    today = date.today()
    grid = st.container(horizontal=True, gap="medium", key="mygrid")
    for show_id_str, entry in list(data["shows"].items()):
        show_id = int(show_id_str)
        show = api(client.get_show, show_id, embed=["nextepisode"])
        episodes = api(client.get_episodes, show_id)
        if show is None or episodes is None:
            continue
        aired = [ep for ep in episodes if logic.is_aired(ep, today)]
        watched = set(entry["watched"])
        done, total = tracker.progress(aired, watched)
        upcoming = tracker.next_unwatched(aired, watched)
        nxt = show.get("_embedded", {}).get("nextepisode")
        card = grid.container(key=f"card-my-{show_id}", width=260)
        up_next = (f'Up next: <b>{esc(logic.episode_code(upcoming))} · {esc(upcoming["name"])}</b>'
                   if upcoming else "<b>You are up to date.</b>")
        airs = f'<div class="card-sub" style="margin-top:4px">New episode {esc(nxt.get("airdate") or "TBA")}</div>' \
            if nxt else ""
        html_block(
            poster_html(show)
            + f'<div class="card-eyebrow">{esc(logic.channel_of(show))}</div>'
            + f'<div class="card-title">{esc(show["name"])}</div>'
            + f'<div class="progress"><div style="width:{(done / total * 100) if total else 0:.0f}%"></div></div>'
            + f'<div class="card-sub">{done} of {total} aired episodes watched</div>'
            + f'<div class="card-sub" style="margin-top:6px">{up_next}</div>{airs}', card)
        card.button("Open", key=f"my_open_{show_id}", on_click=open_show, args=(show_id,), type="tertiary")

    spacer("large")
    with st.expander("Backup: export or import your tracker"):
        st.download_button("Export tracker (JSON)", json.dumps(data, indent=2), file_name="tracker.json",
                           mime="application/json")
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


# ================================================================== crossover

def page_crossover() -> None:
    html_block('<div class="hero"><p class="eyebrow">Cast crossover</p><h1>Who was in both?</h1>'
               '<p class="sub">Pick two shows and see which actors were in the main cast of each.</p></div>')
    c1, c2 = st.columns(2, gap="medium")
    with c1, panel("show-a", "First show"):
        show_a = show_picker("First show", "xa")
    with c2, panel("show-b", "Second show"):
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
    spacer("medium")
    if not shared:
        empty_state(f"No shared main cast between {show_a['name']} and {show_b['name']}.")
    else:
        html_block(f'<p class="panel-title center">{len(shared)} actor{"s" if len(shared) != 1 else ""} '
                   f'in both shows</p><p class="panel-sub center">Main cast only</p>')
        grid = st.container(horizontal=True, gap="medium", horizontal_alignment="center", key="sharedgrid")
        for row in shared:
            person_card(grid, f"shared-{row['person_id']}", {"name": row["name"], "image": row["image"]},
                        [f'{esc(row["character_a"])} <span class="muted">in {esc(show_a["name"])}</span>',
                         f'{esc(row["character_b"])} <span class="muted">in {esc(show_b["name"])}</span>'])
    st.caption("Guest roles are not included: they would need one API call per episode.")


# ================================================================ six degrees

def page_six_degrees() -> None:
    html_block('<div class="hero"><p class="eyebrow">Six degrees of TV</p><h1>How are they connected?</h1>'
               '<p class="sub">Link two actors through shows they starred in: actor → show → actor → …</p></div>')
    c1, c2 = st.columns(2, gap="medium")
    with c1, panel("person-a", "First actor"):
        person_a = person_picker("First actor", "pa")
    with c2, panel("person-b", "Second actor"):
        person_b = person_picker("Second actor", "pb")
    with st.expander("Search settings"):
        s1, s2 = st.columns(2)
        max_shows = s1.slider("Maximum shows in the chain", 1, 3, 3)
        budget = s2.slider("Maximum API calls", 20, 300, 150, step=10,
                           help="Each step costs one call; TVmaze allows about 20 calls per 10 seconds.")
    if not (person_a and person_b):
        return
    _, mid, _ = st.columns([2, 1, 2])
    if mid.button("Find connection", type="primary", width="stretch", key="find"):
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
        st.success(f"Connected through {shows} show{'s' if shows != 1 else ''} after {result['expansions']} lookups")
        parts = [f'<span class="node {n["kind"]}">{"📺 " if n["kind"] == "show" else ""}{esc(n["name"])}</span>'
                 for n in result["path"]]
        html_block('<div class="chain">' + '<span class="arrow">→</span>'.join(parts) + "</div>")
    elif status == "budget":
        st.warning(f"No connection found within {result['expansions']} lookups. Raise the API call limit in "
                   "Search settings and try again.")
    elif status == "too_far":
        st.warning("These two are not connected within the maximum number of shows.")
    else:
        st.info("No connection exists through main-cast roles.")


# ============================================================= higher / lower

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
    html_block('<div class="hero"><p class="eyebrow">Higher or lower</p><h1>Which one rates higher?</h1>'
               '<p class="sub">Guess which show has the better TVmaze rating. One wrong guess ends your streak.</p></div>')
    if "game" not in st.session_state:
        shows = []
        for page in (0, 1, 2):
            shows += api(client.get_shows_page, page) or []
        pool = logic.game_pool(shows) or logic.game_pool(shows, min_weight=0)
        if len(pool) < 2:
            st.error("Could not load enough shows to play.")
            return
        st.session_state.game = {"pool": pool, "rng": random.Random(), "seen": set(), "score": 0,
                                 "pair": None, "answer": None}
        new_round()

    game = st.session_state.game
    kpis([("Current streak", str(game["score"]), "correct in a row"),
          ("Best ever", str(data["settings"]["game_best"]), "saved on this computer")])

    left, vs, right = st.columns([5, 1, 5], gap="medium")
    for col, show, choice in ((left, game["pair"][0], "a"), (right, game["pair"][1], "b")):
        card = col.container(key=f"card-game-{choice}")
        html_block(poster_html(show) + f'<div class="card-eyebrow center">{esc(logic.channel_of(show))} · {esc(logic.year_of(show))}</div>'
                   f'<div class="card-title center" style="font-size:1.25rem">{esc(show["name"])}</div>'
                   f'<div class="center">{pills(*(show.get("genres") or [])[:3], kind="blue")}</div>', card)
        if game["answer"] is None:
            card.button("This one is rated higher", key=f"guess_{choice}", on_click=guess, args=(choice,),
                        type="primary")
        else:
            html_block(f'<div class="reveal">★ {logic.rating_of(show):.1f}</div>', card)
    html_block('<div class="vs">vs</div>', vs)

    if game["answer"] is not None:
        _, mid, _ = st.columns([2, 1.2, 2])
        if game["answer"]:
            html_block('<div class="result ok">Correct!</div>', mid)
            mid.button("Next round", on_click=new_round, type="primary", width="stretch")
        else:
            html_block(f'<div class="result bad">Wrong. Your streak was {game["score"]}.</div>', mid)
            mid.button("Play again", on_click=restart, type="primary", width="stretch")


# ===================================================================== about

def page_about() -> None:
    html_block('<div class="hero"><p class="eyebrow">About</p><h1>How it works.</h1>'
               '<p class="sub">Built on the free TVmaze API. No account, no API key.</p></div>')
    with panel("about", "One client for every call",
               "tvmaze/client.py caches responses for an hour, keeps to 18 calls per 10 seconds, and retries "
               "when TVmaze answers 429 Too Many Requests."):
        st.markdown(
            """
| Feature | TVmaze endpoints |
|---|---|
| Search, show page | `/search/shows`, `/shows/:id?embed[]=nextepisode` |
| All episodes, heatmap, binge plan | `/shows/:id/episodes` (`?specials=1` for specials) |
| Cast, crossover | `/shows/:id/cast` |
| Six degrees | `/search/people`, `/people/:id/castcredits?embed=show`, `/shows/:id/cast` |
| Higher or lower | `/shows?page=N` |
""")
        st.caption(f"Your followed shows and watched episodes are stored locally in data/tracker.json. "
                   f"Network calls made since the app started: {client.network_calls}")


# ================================================================ navigation

st.markdown(f"<style>{(HERE / 'style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
html_block('<div class="brand">📺 TV Show <span>Explorer</span></div>')
nav = st.container(key="nav")
page = nav.radio("Navigation", PAGES, key="page", horizontal=True, label_visibility="collapsed")

{
    "Search": page_search,
    "My shows": page_my_shows,
    "Crossover": page_crossover,
    "Six degrees": page_six_degrees,
    "Higher or lower": page_game,
    "About": page_about,
}[page]()

html_block('<div class="foot">Data from <a href="https://www.tvmaze.com" target="_blank">TVmaze</a>, '
           'licensed under <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank">CC BY-SA 4.0</a>.'
           '</div>')
