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
python3 -m tools.explorer_browser_diagnostic --real-browser \
  --graph-profile small --scenario during-consumption --observer-mode verified \
  --samples 1 --viewport 1280x720 --output /owned/evidence/contention-verified.json
python3 -m tools.explorer_browser_diagnostic --real-browser \
  --graph-profile small --scenario during-consumption --observer-mode native-json \
  --samples 1 --viewport 1280x720 --output /owned/evidence/contention-native.json
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
`process-cold`, **not disk-cold**. The diagnostic measures browser-performance milestones; the clock origin is
navigation and comparisons stay within the same browser sample. Request elapsed
ends at fetch headers, not body completion. The `verified` observer consumes one
body via text, separates body/decode, JSON parse, UTF-8 encoding/hash verification,
buildMoodGraphModel and scene submission start/end timestamps. The model span
covers that function only, not all downstream filter preparation or loading-state
work before nextFrame/renderMap. Gaps remain unattributed; subtracting isolated
spans cannot establish full CPU/GPU attribution. Verification adds
observer overhead; model duration excludes that verification, but neither is an
uninstrumented production timing. The scene interval wraps synchronous renderMap
work inclusively (signatures, copies, layout, mood strip and graphData submission);
it is not isolated graphData or GPU timing. No cloned or second body is consumed.

The observer-light `native-json` mode uses native response.json and records its
inclusive start/end. Separate body/decode and parse timings are unavailable;
consumed identity unavailable means bytes/hash are null. Fixture manifest identity
is not substituted for the consumed response identity. Native decoded node/link
counts remain available. Compare modes only with matched source/environment and
retain each mode label; do not call their difference a product improvement.

`graph_first_presentation` is a next-frame presentation proxy after scene
submission, not proof of physical display, earliest useful pixels, first paint,
pixel verification, or GPU time. The separate
`graph_post_focus_readback` records forced render/readPixels verification after
focus. Legacy usable-render denotes this later check, not earliest presentation.
Finite camera, selected center in viewport and halo observations do not certify
useful projected scale, visual quality or smoothness. Long tasks carry start/end
and duration. A task may intersect several phases: overlap is not causation and
must not be summed as exclusive phase costs. GPU time remains explicitly null;
SwiftShader is software rendering, not physical-GPU evidence. RSS is unavailable
unless measured with a declared process-tree scope; unavailable is null, not zero.

The during-consumption contention scenario releases held headers and an initial
gzip byte, waits for active body/native-json consumption, and attempts trusted
input while the remaining body is deliberately paced. It then reobserves active
consumption and records selection intent before releasing the remainder and
issuing the trusted superseding selection. Paced network waiting is not itself
CPU contention; only actual browser receipt timestamps and phase spans can show
where receipt overlapped or was queued behind parse/model/scene work. Host dispatch uses host monotonic
clock; browser event receipt and next frame use browser-performance clock. Do
not subtract these different clocks. An attempted dispatch is not receipt or
success, and a queued event may be handled after synchronous work completes.
The report retains attempts and null missing receipt/frame data on timeout;
synchronous page.evaluate callbacks cannot manufacture concurrent input.
`contention_status` is `observed-trusted-input` only when both host actions have
trusted receipt and valid ordered frame observations. Missing observations remain
`unavailable`; malformed chronology is `invalid_response`. A sample's lifecycle
`outcome=ok` can coexist with unavailable contention telemetry: lifecycle success
is not successful contention observation or evidence of responsiveness.

Failed attempts and retry failures remain live observations; live reports retain
individual samples and counts rather than computing percentile profiles. A browser
launch, page creation or WebGL preflight failure is retained as a classified
lifecycle failure with null unobserved milestones, without exception text; earlier
completed samples survive. Observed flow failures also survive a later lifecycle
timeout, counted per failed request rather than again for its retry UI. Invalid
render or focus produces a failure summary. Existing held-pending scenarios require
exactly one consumed focus; latest-selection additionally requires the latest halo
identity. During-consumption with an observed trusted supersession requires at
least one observed focus start and the latest accepted final halo. An initial focus can begin before queued supersession
cancels/replaces it, so more than one start is not itself failure; retain the count.
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

## Observation-only acceptance and public evidence

This PR supplies instrumentation, not a responsiveness optimization. Issue #70
remains open. Bounded single-sample correctness observations do not complete the
inherited proposed 5/20 process-cold/warm comparison campaign or establish p95
guarantees. Numerical performance targets and representative dataset acceptance
require owner agreement. Public evidence must retain failures, observer mode,
source revision, exact sample counts, fixture provenance, renderer and unavailable
metrics. Publish allowlisted numeric fields and fixed labels only, never private
identifiers, paths, arbitrary errors, payloads, screenshots or response bodies.
Server phases, SQLite attribution and private-library speed remain unmeasured.
