# TV Show Explorer

A Streamlit web app with an Apple-inspired design, built on the free [TVmaze API](https://www.tvmaze.com/api). Search any TV show, list **all of its episodes**, and do more with that data than the API offers on its own: rating heatmaps, a binge planner, a watch tracker, cast crossovers, "six degrees" between actors and a small game.

## Features

| Feature | What it does |
|---|---|
| **Search & all episodes** (required) | Fuzzy search for a show, open it, and see every episode grouped by season with air date, runtime, rating and summary. Specials can be switched on. |
| Rating heatmap | One coloured cell per episode (season × episode) to spot the best and weakest stretches; plus season averages and best / worst episode. |
| Binge plan | Total watch time and your finish date, given minutes per day, viewing weekdays and a start point (first episode, your next unwatched one, or any episode). |
| Watch tracker | Follow shows, tick off episodes (or whole seasons), see progress and "up next" on *My shows*. Export / import as JSON. |
| Spoiler-free mode | Hides summaries of episodes you have not reached yet. |
| Cast crossover | Pick two shows and see which actors were in the main cast of both, and whom they played. |
| Six degrees of TV | Connects two actors through shared shows (actor → show → actor …) with a bidirectional breadth-first search. |
| Higher or lower | Guess which of two shows has the higher TVmaze rating; keeps your best streak. |

## Run it

Needs Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501. No API key or account is needed.

## How it uses the API

TVmaze is a read-only REST API: every endpoint is a `GET` that returns JSON. These are the ones the app uses:

| Endpoint | Used for |
|---|---|
| `GET /search/shows?q=` | Show search (fuzzy, best match first) |
| `GET /shows/:id?embed[]=nextepisode` | Show page; `embed` adds the next airing episode in the same call |
| `GET /shows/:id/episodes` (`?specials=1`) | All episodes, heatmap, binge plan, tracker |
| `GET /shows/:id/cast` | Cast tab, crossover, six degrees |
| `GET /search/people?q=` | Actor search for six degrees |
| `GET /people/:id/castcredits?embed=show` | An actor's shows, for six degrees |
| `GET /shows?page=N` | Show index (250 IDs per page), for the game |

**One client for every call.** No page talks to TVmaze directly; everything goes through `tvmaze/client.py`:

- **Rate limit:** TVmaze allows about 20 calls per 10 seconds. The client keeps to 18 and waits when needed.
- **Retries:** on `429 Too Many Requests` it waits 2, 4 and 8 seconds before giving up.
- **Cache:** identical requests are answered from memory for an hour (24 h for the show index). TVmaze itself caches for 60 minutes, so fresher data is not possible anyway.
- **Errors:** 404, rate limits, server and network errors become typed exceptions (`NotFoundError`, `RateLimitError`, `ApiError`), shown as a message in the app instead of a crash.

## Project structure

```
app.py                  Streamlit UI: all pages and navigation
style.css               Apple-inspired design: system font, light grey canvas, white cards, one blue accent
.streamlit/config.toml  Streamlit theme matching style.css
tvmaze/client.py        HTTP client: endpoints, cache, throttle, retries, errors
tvmaze/logic.py         Pure functions: episode grouping, heatmap, binge plan, crossover, six degrees, game
tvmaze/tracker.py       Watch tracker stored in data/tracker.json (git-ignored)
tests/                  pytest suite, runs without internet
.github/workflows/      Runs the tests on every push
```

The split keeps the logic testable: `logic.py` and `tracker.py` never touch the network or Streamlit.

## Design decisions and limitations

- **No backend or database.** TVmaze has no user accounts in its public API, so the watch tracker is a local JSON file. It stays on your machine; use Export / Import to move it.
- **Main cast only** for crossover and six degrees. Guest roles would need one API call per episode, which the rate limit does not allow.
- **Six degrees has a budget.** Each step is one API call, so the search stops after a set number of calls (default 150) and at most 3 shows.
- **Ratings can be missing** on smaller shows; those cells stay grey in the heatmap.
- **Binge plan counts aired episodes only.** Announced future episodes are listed but not counted.

## Tests

```bash
python -m pytest -q
```

46 tests, no internet needed:

- `test_client.py`: a fake HTTP session checks caching, cache expiry, throttling, 429 retries, 404s and network errors.
- `test_logic.py`: episode grouping, heatmap data, binge maths, crossover, six degrees on a small fake TV world, game rules.
- `test_tracker.py`: saving, loading, corrupt files, follow / watched / progress.
- `test_app.py`: runs the Streamlit app against a fake TVmaze and clicks through search → show → all episodes (with and without specials), following and ticking episodes, crossover, six degrees, the game and every other page.

## Credits

Data from [TVmaze](https://www.tvmaze.com), licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Built with help from Claude (Anthropic) as a coding assistant.
