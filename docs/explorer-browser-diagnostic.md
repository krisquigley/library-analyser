# Public synthetic browser diagnostic (issue #70, PR4d)

This developer-only outward tool runs real Playwright Chromium against packaged
Explorer assets on an owned ephemeral loopback server. It accepts no private
catalogue, database path, remote URL, audio, or arbitrary server target. It does
not change packaged runtime behavior. Synthetic state/search/detail identifiers
match positioned graph nodes; graph bytes do not come from SQLite.

## Explicit invocations

Install Playwright and its Chromium channel outside the repository, then run
only under the externally bounded supervision described below:

```sh
python3 -m tools.explorer_browser_diagnostic --real-browser \
  --graph-profile small --scenario pending-then-ready --samples 1 \
  --viewport 1280x720 --output /owned/evidence/small.json
python3 -m tools.explorer_browser_diagnostic --real-browser \
  --graph-profile stress-41mib --allow-large --scenario pending-then-ready \
  --samples 1 --viewport 1280x720 --output /owned/evidence/large.json
```

The small fixture has 12 nodes and 11 chain links. The explicit large profile
has 20,000 nodes and 19,999 chain links, no unpositioned nodes, and exactly
41 * 2**20 decoded JSON bytes. Explanation inflation makes this a deterministic
public browser-only stress fixture, not catalogue realism or writer-generated
database evidence. Canonical decoded hashes and exact same-runtime gzip encoded
hashes/counts are verified independently. Compression ratios depend on runtime.
Samples are exact integers 1–100. Large execution requires both profile choice
and `--allow-large`; no opt-in skip is completed browser acceptance.

Scenarios include `pending-then-ready`, `graph-failure-retry`, `search-failure`,
and `latest-selection`. The first three retain graph/search failures and retries
while verifying search rows, accepted current selection and detail before held
graph delivery, then real graph render and focus. Latest-selection additionally
checks a newer accepted selection supersedes the older pending focus intent.

## Execution safety

Before launching, independently verify the effective cgroup `memory.max` is a
positive value at most 4 GiB, `memory.swap.max` is zero and `memory.oom.group`
is 1. Record actual limits and memory.events before and after. A missing browser,
failed WebGL preflight, unbounded environment, OOM, deadline, or scratch-limit
failure is a blocker/failure, never intended RED or a successful skip. Chromium
reserves large virtual address ranges: do not use RLIMIT_AS as a browser RAM cap.
Use Podman for any container operations; never fall back to Docker.

Supply a writable `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` inside a parent-owned
scratch directory without changing HOME or browser flags. Disable core dumps.
Use an external hard wall deadline, per-file size cap and aggregate scratch
monitor. The validated evidence supervisor uses 32 MiB per file and 128 MiB
aggregate scratch (sampled monitoring, not filesystem quota), with no silent cap
increase. Output reports belong in a separate owned evidence directory. Chromium
profiles/config/cache remain in scratch and are deleted even on failure.

Cleanup must SIGKILL the owned process group and independently tracked
descendants, including children that change session; a Linux child-subreaper
reaps adopted orphans. Verify no descendants survive and remove all owned
scratch after normal completion and timeout. A plain shell timeout alone is
not sufficient supervision. This repository's tool is not an aggregate scratch
quota or external wall-time supervisor; these remain caller responsibilities.
Do not retain screenshots, HAR, response bodies or crash dumps as evidence.

## What reports mean

Live evidence identifies real-playwright-chromium, viewport, browser/Python/
platform versions, fixture hashes/counts and sample count. Fresh browsers are
`process-cold`, **not disk-cold**. The diagnostic measures browser-performance
milestones for navigation, graph request/headers/body/JSON/model/usable render,
search input/rows, selection feedback/detail and focus start/end; the clock
origin is navigation and comparisons stay within the same browser sample.
Per-request `elapsed_ms` ends at fetch headers, not body completion; graph body
and JSON completion have separate milestones. Browser-consumed UTF-8 byte/hash
and JSON-count checks happen after parse and before model handoff; encoding and
digest work add observer overhead. Their duration is not separately attributed.
Frame gaps, frame count, long-task observations and input-to-frame observations
are observer-on browser data, not uninstrumented production timings.
Canvas/nonempty-pixel, positioned-node, finite-camera, selected-node-in-view and
halo observations support render/focus acceptance; they are not subjective
visual quality certification. The usable-render timestamp confirms a GPU frame
after focus, not the earliest graph presentation; do not interpret it as first
paint or an isolated render-phase duration. RSS is explicitly unavailable unless measured
with a declared process-tree scope; unavailable is null, not zero.

Failed attempts and retry failures remain live observations; live reports retain
individual samples and counts rather than computing percentile profiles. A browser
launch, page creation or WebGL preflight failure is retained as a classified
lifecycle failure with null unobserved milestones, without exception text; earlier
completed samples survive. Observed flow failures also survive a later lifecycle
timeout, counted per failed request rather than again for its retry UI. Invalid
render or focus produces a failure summary, and success requires exactly one
consumed focus; latest-selection additionally requires the latest halo identity.
A written report (or zero CLI exit) does not imply a successful browser sample. In the
supplied-observation policy only, successful durations alone enter nearest-rank
p50/p95/max; an all-failed profile has null percentiles. Small samples do not
establish robust distributions. The separate
`publish_browser_report` supplied-observation API always labels its output
`supplied-observations-not-browser-acceptance`; it cannot manufacture real-browser
evidence. It allowlists labels/numeric fields and drops arbitrary environment,
payloads, targets, query strings, handles and paths. Missing milestones stay
null; reversed intervals remain flagged after sanitization.

This is not a latency budget, SQLite query-speed measurement, real-library
responsiveness guarantee, isolated server-phase timing, or issue #70 completion
claim. No universal speed or memory-cap claim follows from one public fixture.

## Focused checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
 tests.unit.benchmark_tools.test_explorer_browser_graph_fixture \
 tests.unit.benchmark_tools.test_explorer_browser_docs \
 tests.acceptance.test_explorer_browser_diagnostic
RUN_EXPLORER_BROWSER_DIAGNOSTIC=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
 tests.acceptance.test_explorer_browser_diagnostic
RUN_EXPLORER_BROWSER_DIAGNOSTIC=1 RUN_EXPLORER_BROWSER_DIAGNOSTIC_LARGE=1 \
 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
 tests.acceptance.test_explorer_browser_diagnostic
```

Run the real commands through the same bounded supervisor, not unbounded shells.
Default tests execute tiny CLI/report contracts without browser acceptance.
The large unit oracle additionally needs RUN_EXPLORER_BROWSER_GRAPH_LARGE=1.
Run architecture checks locally; full CI owns full-suite verification.
