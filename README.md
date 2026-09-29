# spacex-launches

Display SpaceX launches of a given UTC day in the terminal, using the
[rich-ui](https://github.com/janmaru/mahamudra-rich-ui) DSL renderer.

The data comes from [Launch Library 2](https://ll.thespacedevs.com/) (The Space
Devs). The older API `api.spacexdata.com` has not been updated since 2022 and
does not include recent launches.

## Requirements

- Python 3.10+
- Git (pip installs `rich-ui` straight from GitHub)
- Internet connection on first run (Launch Library 2 fetch + cache storage)

## Quick start

```powershell
Set-Location C:\Coding\spacex-launches
.\setup.ps1
.\.venv\Scripts\Activate.ps1

python main.py
```

On first run, `setup.ps1` creates a virtual environment and installs the
dependencies from `requirements.txt`, including `rich-ui` from
[GitHub](https://github.com/janmaru/mahamudra-rich-ui). Without the script:
`pip install -r requirements.txt`. The app downloads launches from Launch
Library 2 and caches them to `cache/`. Later runs use the cache.

## CLI options

| Option | Values | Default | Description |
|---|---|---|---|
| `--date` | YYYY-MM-DD | today (UTC) | The UTC day to display |
| `--view` | `dashboard` `panel` `compact` | `dashboard` | Rendering mode |
| `--offline` | flag | — | Use cache only, no network request |
| `--refresh` | flag | — | Ignore the cache and download again |
| `--cache-dir` | path | `cache/` | Cache directory |
| `--dump-mocks` | path | — | Write spec/data/sync to DIR as `spacex.json`, `spacex.data.json`, `spacex.sync.json` |
| `--open-timeline` | flag | — | Open the native mission timeline viewer immediately and exit (scripts/pipes) |

Examples:

```powershell
python main.py                           # Today, dashboard view
python main.py --date 2026-09-28         # Specific day
python main.py --view panel              # Panel-only view
python main.py --offline                 # Cache only
python main.py --refresh                 # Re-download
python main.py --dump-mocks ./mocks      # Write mock files
python main.py --open-timeline           # Native viewer (exit code 4 on error)
```

> **Note**: Dates are in UTC. A launch after 22:00 Italy time (summer) falls
> on the next UTC day. Times outside the requested day are shown with the prefix
> `mm-dd`.

### Native mission timeline viewer (`T` key)

After printing the dashboard, the app listens for keyboard actions declared in
the DSL: press **`T`** to open the mission timeline in a **Tkinter** window,
**`Q`** to quit.

The window draws the mission phases on a linear time axis from T-0 (dashed
yellow line), on three lanes: countdown (white squares), ship (cyan diamonds),
booster (magenta circles). Each event is
labeled with `name  T±hh:mm:ss`; labels stack on up to four levels to avoid
overlap. Mouse wheel zooms around the cursor, drag pans, **R** resets the view,
**ESC** closes the window. The window respects the `--date` selected and plots
the **first launch of that day**.

Key listening is active only on an interactive terminal; with redirected output
(pipe/script) use the `--open-timeline` flag, which opens the viewer directly
without waiting for `T`. Requires Tkinter (bundled with Python on Windows); if
unavailable, a warning is printed but the app does not exit.

## Documentation

- **[TECHNICAL_ANALYSIS.md](docs/TECHNICAL_ANALYSIS.md)**: how the system works
  (architecture, data flow, parser, caching, components)
- **[FUNCTIONAL_ANALYSIS.md](docs/FUNCTIONAL_ANALYSIS.md)**: what the UI shows
  and how to read it (meaning of values, interpreting the timeline, reading the
  scatter)

## The Launch Library 2 query

Defined in `spacex_launches/fetcher.py`:

| Parameter | Value | Meaning |
|---|---|---|
| `lsp__name` | `SpaceX` | Organization filter |
| `net__gte`, `net__lte` | YYYY-MM-DD window | UTC day range (00:00:00 to 23:59:59 Z) |
| `limit` | `20` | Results per page |
| `mode` | `detailed` | Full launch object (includes `timeline`) |
| `ordering` | `net` | Sort by Net Time (T-0 timestamp) |

The API is paginated; if a day has more than 20 launches, the app follows the
`next` link up to 10 pages (max 200 launches) and merges them. The raw response
is cached to avoid repeated API calls; rate limiting is enforced by LL2 at a
few dozen requests per hour for anonymous users.

## Structure

```
spacex-launches/
├── main.py                  # CLI + orchestration (fetch → adapter → render)
├── requirements.txt         # rich, requests, rich-ui
├── README.md                # this file
├── setup.ps1                # venv setup + dependency install
├── .gitignore               # cache/, .venv/, generated payloads
├── docs/                    # documentation
│   ├── TECHNICAL_ANALYSIS.md  # how the system works (architecture, flows)
│   └── FUNCTIONAL_ANALYSIS.md  # what the UI shows (meaning of data, reading)
├── cache/                   # YYYY-MM-DD.json files (git-ignored)
├── mocks/                   # snapshot of Starship Flight 14 (Sep 28, 2026)
│   ├── spacex.json          # DSL spec (static)
│   ├── spacex.data.json     # data payload (example)
│   └── spacex.sync.json     # sync payload (freshness metadata)
├── specs/                   # DSL definitions
│   ├── spacex.json          # static spec (layout, structure)
│   ├── spacex.data.json     # generated at runtime
│   └── spacex.sync.json     # generated at runtime
└── spacex_launches/
    ├── __init__.py
    ├── adapter.py           # LL2 response → DSL payload
    ├── fetcher.py           # LL2 API + cache management
    ├── timeline.py          # phase parsing (ISO 8601 durations → timeline)
    └── viewer.py            # native Tkinter mission timeline viewer
```

## Data source

[Launch Library 2 API](https://ll.thespacedevs.com/) — launches with timelines,
no authentication required.

## TODO

- **Starlink orbital trajectory.** LL2 does not provide state vectors. Would
  need [CelesTrak](https://celestrak.org/) TLEs for newly deployed satellites
  and SGP4 propagation (e.g. the `sgp4` package) to render orbital tracks in the
  `scatter_2d` and the native Tkinter viewer, like in mahamudra-Oumuamua.
- **Extended phase descriptions from SpaceX CMS.** The page
  `spacex.com/launches/<slug>` is an Angular app that fetches from
  `https://content.spacex.com/api/spacex-website/missions/<slug>` (no auth). The
  JSON includes `preLaunchTimeline` and `postLaunchTimeline` with more readable
  descriptions than LL2, e.g. "Max Q (moment of peak aerodynamic stress on the
  rocket)". Would require a second cache and mapping between LL2 launch and
  SpaceX slug.
