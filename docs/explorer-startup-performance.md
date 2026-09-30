# Explorer startup performance contract

This note defines the public-safe startup performance contract for the Track Journey Explorer. It uses only generated SQLite rows and generated track labels. It must not use a live user analysis database, Mixxx database, audio files, private filesystem paths, private filenames, or raw logs.

## User-visible goal

For large libraries, the first usable explorer view is the track list and basic controls. The browser must be able to show that view from a compact summary page without waiting for graph construction or full per-track evidence parsing.

Product decision: the graph is manually requested. The first view shows a visible **Load graph** button; the browser must not request `/api/mood-axis-graph` on initial startup at any library size. Clicking the button starts graph loading with independent loading/error/retry state while the compact list, search, selection, history, and detail interactions remain usable.

The existing full-library endpoints remain compatibility endpoints. New startup work should use a paginated summary endpoint for the initial list, then load graph data only after the user activates the graph button.

## Public synthetic benchmark methodology

The acceptance benchmark in `tests/acceptance/test_explorer_startup_performance.py` creates temporary synthetic databases with:

- 5,000 and 20,000 active tracks.
- Generated `sha256:` handles.
- Generated title/artist metadata (`Track 00000`, `Synthetic Artist 00`, and so on).
- Generated locations under a synthetic root string only.
- No audio files and no user database reads.

The benchmark then starts the local explorer server on loopback and records cold and warm request behavior for the summary page:

```text
GET /api/tracks/summary?limit=100&order=title
```

The browser smoke portion is opt-in with `RUN_BROWSER_SMOKE=1`. When Playwright/Chromium is available, it verifies that a generated track button and the search control become usable without any graph request, checks simple search/selection interactions before graph loading, then clicks **Load graph** and verifies independent graph loading/error/retry behavior where feasible.

## Startup targets

| Area | Target |
| --- | --- |
| Summary page size | Each 100-row JSON page is <= 150 KiB for 5k and 20k synthetic libraries. |
| Summary API bounds | `limit` is bounded, query text is bounded, order is explicit, and the response carries `next_cursor` when another page exists. |
| Startup data shape | Track-list startup JSON contains only handle, title, artist, display label, available-location count, metadata, limit, cursor, query, and order. |
| Heavy reads | Initial list loading does not call full `candidate_snapshot`, does not read full track details, and does not parse stored stage `result` payloads. |
| First usable browser view | With a browser available, track list/search controls render and remain interactive without requesting the graph; graph loading starts only after the user clicks **Load graph**, with visible loading/error/retry state. |

## Baseline aggregate observations

These aggregates are from the public synthetic harness, not from a user library. They illustrate the previous full-library startup cost that the summary contract is intended to avoid.

| Synthetic library | Endpoint | Cold payload | Warm payload | Aggregate observation |
| --- | --- | ---: | ---: | --- |
| 5,000 tracks | `/api/tracks?limit=all` | ~12.4 MiB | ~12.4 MiB | Full-library JSON was far above the 150 KiB page target. |
| 20,000 tracks | `/api/tracks?limit=all` | not bounded by startup target | not bounded by startup target | Full-library startup did not provide a compact first page and is unsuitable as the first usable view contract. |
| 5,000 tracks | `/api/tracks/summary?limit=100&order=title` | <= 150 KiB target | <= 150 KiB target | Acceptance target for the new summary contract. |
| 20,000 tracks | `/api/tracks/summary?limit=100&order=title` | <= 150 KiB target | <= 150 KiB target | Acceptance target for the new summary contract. |

Only aggregate sizes and pass/fail targets belong in this document. Do not paste raw benchmark logs, private hostnames, local checkout paths, user music filenames, database paths, or results from a real personal library.

## How to run the synthetic checks

Run the non-browser acceptance benchmark:

```bash
python3 -m unittest tests.acceptance.test_explorer_startup_performance -v
```

Run the optional first-usable-view browser check only when Playwright and a browser are intentionally available:

```bash
RUN_BROWSER_SMOKE=1 python3 -m unittest tests.acceptance.test_explorer_startup_performance.ExplorerStartupPerformanceAcceptanceTests.test_browser_reaches_first_usable_track_list_before_graph_response -v
```

Use Podman for any containerized execution in this repository. Do not use Docker.

## Limitations

- Synthetic rows are designed to exercise startup payload size, pagination, and UI sequencing. They do not predict absolute timings for every production machine.
- Browser timing is intentionally opt-in because CI runners may not have Chromium or WebGL available.
- The optional browser check can measure interaction latency before graph loading and, when feasible, while a user-triggered graph request is pending. It does not fully measure responsiveness during CPU-bound graph layout/rendering after a large graph response arrives.
- The current graph path can take more than 45 seconds of CPU-bound work on large libraries. The manual button keeps that work outside initial startup, but graph speed remains a known limitation and needs separate future graph algorithm and rendering work.
- Compatibility endpoints may remain slower or larger; the startup contract applies to the summary path used for initial rendering.
