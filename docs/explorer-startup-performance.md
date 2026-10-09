# Explorer startup performance contract

This note defines the public-safe startup performance contract for the Track Journey Explorer. It uses only generated SQLite rows and generated track labels. It must not use a live user analysis database, Mixxx database, audio files, private filesystem paths, private filenames, or raw logs.

## User-visible goal

For large libraries, the first usable explorer view is an empty search sidebar and basic controls. Startup, refresh, undo and reset do not fetch a list merely to fill the sidebar. A nonblank search requests a bounded compact summary page without waiting for graph construction or full per-track evidence parsing; blank or whitespace input clears results immediately. Loading, no matches and retryable search/page errors are scoped to the sidebar. Pagination is explicit and stale query/page responses cannot replace newer search intent.

Product decision: the graph loads automatically. Startup starts one `/api/mood-axis-graph?contract=v3` request independently of state, search and selected-track detail requests; no manual **Load graph** action is required. Successful data renders automatically, with inline loading/rendering feedback and a scoped error/retry state. Slow or failed graph requests must not block search, selection, history or detail interactions; failed state or search requests must not prevent graph completion or leave a blocking startup overlay. Graph completion must not replace search results or current details. Refresh, undo and reset do not restart graph loading. After the graph is ready, a user-initiated mood change reloads the graph for the selected mood while preserving the existing layout/camera when the returned graph geometry is unchanged.

The existing full-library endpoints and blank-query summary API remain compatibility endpoints. The browser uses the paginated summary endpoint only for nonblank searches. Automatic graph startup extends the search-first lifecycle from issue #70 PR1 without changing graph response contracts, topology, active-track eligibility or evidence validation. Independent request lifecycles are not a guarantee of CPU responsiveness during large-response parsing or rendering.

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

The browser smoke portion is opt-in with `RUN_BROWSER_SMOKE=1`. When Playwright/Chromium is available, it verifies that the search control becomes usable with no initial sidebar request while an automatic graph request is pending, then searches for generated tracks and checks selection interactions without waiting for graph completion. Focused Node lifecycle tests cover automatic success, failure/retry and independence from deferred or failed requests; they do not replace real-browser responsiveness measurements.

## Startup targets

| Area | Target |
| --- | --- |
| Summary page size | Each 100-row JSON page is <= 150 KiB for 5k and 20k synthetic libraries. |
| Summary API bounds | `limit` is bounded, query text is bounded, order is explicit, and the response carries `next_cursor` when another page exists. |
| Search data shape | Nonblank-search summary JSON contains only handle, title, artist, display label, available-location count, metadata, limit, cursor, query, and order. |
| Heavy reads | Startup issues no sidebar list request. Search summaries do not call full `candidate_snapshot`, read full track details, or parse stored stage `result` payloads. |
| First usable browser view | With a browser available, the empty sidebar/search controls render and remain interactive without a sidebar list request while the automatic v3 graph request is pending; graph loading/rendering/error/retry feedback is scoped inline. |

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

Run the focused Node lifecycle checks with Node installed (a Node skip is not acceptance evidence):

```bash
command -v node >/dev/null && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.acceptance.test_explorer_auto_graph_startup \
  tests.acceptance.test_explorer_auto_graph_independence
```

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
- The optional browser check exercises interactions while the automatic graph request is pending. It does not fully measure responsiveness during CPU-bound parsing, model building or graph rendering after a large graph response arrives. Browser skips are not passing browser acceptance evidence.
- Large-library graph work remains a known limitation. Automatic startup can overlap bandwidth, CPU and memory costs with other interactions; deferred-response Node tests do not measure those costs. This lifecycle change makes no graph-speed claim and does not resolve issue #44. A representative 41 MiB-class real-browser response scenario still requires separately reported measurements.
- Compatibility endpoints may remain slower or larger; the bounded-response contract applies to the summary path used for nonblank search results.
