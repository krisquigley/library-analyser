# Public synthetic browser diagnostic (issue #70, PR4d)

This developer-only outward tool runs real Playwright Chromium against packaged
Explorer assets on an owned ephemeral loopback server. It accepts no private
catalogue, database path, remote URL, audio, or arbitrary server target. It does
not change packaged runtime behavior. Synthetic state/search/detail identifiers
match positioned graph nodes; the default browser-only mode's graph bytes do not
come from SQLite. The separate writer-v10 mode described below owns a public
writer-created SQLite fixture and uses the actual packaged Explorer server.

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
payloads, targets, query strings, handles and paths. Supplied `observed-trusted-input`
is retained only for exactly two sanitized observations with distinct `input` and
`selection` actions, `outcome=ok`, literal trusted receipts on the browser-performance
clock, and finite nonnegative receipt/frame times with frame at or after receipt.
Invalid or missing observations downgrade the claim and cannot retain per-record
`ok`; explicit unavailable/failure outcomes are never upgraded. Host intent is not
compared with browser receipt time. This validation still does not establish
actual browser acceptance or causal contention. Missing milestones stay
null; reversed intervals remain flagged after sanitization. Supplied responsiveness
retains `long_tasks_status` only as `observed` or `unavailable`; absent or invalid
status defaults to `unavailable`. An empty `long_tasks` list with `observed` means
an observed zero-task interval, not unavailable collection. This availability label
does not establish browser acceptance or change overlap-not-causation attribution.

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
In browser-only mode, server phases and SQLite attribution remain unmeasured.
Private-library speed remains unmeasured in every mode.

## Writer-v10 packaged-server detail bridge (issue #70, PR C)

The opt-in writer mode composes `public_synthetic_fixture`, the real
`create_server` loopback adapter, packaged assets and Chromium/WebGL. Its report
scope is `public-synthetic-sqlite-browser`, distinct from browser-only inflated
41 MiB stress. The fixture's owned writer manifest is database provenance; it
must not be replaced with browser-only provenance. Main/WAL fingerprints bracket
reader activity. No private database, audio or remote-target options are added.
Generated fixture scratch and browser scratch have separate resource envelopes;
do not borrow the browser scratch cap for larger database profiles or silently
increase it. Use tiny fixtures first and retain external containment records.

Each `detail_bridge` sample publishes only fixed metadata, bounded numeric
observations, booleans and locally relabeled request identities. The observer
correlates the trusted selected-row intent with POST body/acceptance, matching
GET URI/response and rendered detail DTO internally. Handles, raw JSON, unknown
strings, filesystem paths and exception text are not published. Consumed graph
bytes/SHA describe the actual received entity, separate from the writer manifest;
semantic graph validation uses the fixture oracle. Detail identity is correlated
handle/DTO/DOM evidence, not an independent detail entity hash.

Browser receipt, loading DOM mutation, loading next-frame observation, POST
request/headers/body/parse, GET request/headers/body/parse, detail DOM-ready and
detail next-frame proxy remain distinct browser-performance observations. Only
same-clock operands may define selection elapsed. Loading-frame busy may be
false: this is not proof of feedback before POST acceptance, contention
responsiveness or physical paint. Text/parse/hash observation adds overhead;
software WebGL is not evidence of physical GPU speed.

Supplied publication contracts are policy tests, not executed browser scenarios.
Publication retains every failure and partial observation, nulls malformed fields
and rejects inconsistent claimed success before successful-duration aggregates.
Acceptance requires POST acceptance before matching GET, coherent phase order,
latest sequence, no initial summary/unrelated detail/unapproved graph refetch,
unchanged database and owned cleanup. One explicitly observed graph retry is
accepted only with two requests, `graph_retry_count=1` and ordered
`graph_attempt_outcomes=["http_error", "ok"]`; arbitrary extra requests remain
invalid and initial failure evidence is retained. Browser/server/scratch cleanup flags describe owned
contexts; they do not replace external tracked-descendant/subreaper cleanup
proof. Server phases in the bridge remain explicitly unavailable. The existing
server microprofiler supplies separately sanitized top-level `server_observation`
request-local spans on the server-process monotonic clock. Browser-to-server
request correlation is explicitly unavailable; no matching is fabricated from
order or cross-clock subtraction. These spans belong to their own clock/scope
and must not be subtracted from browser operands.

The tiny real gate is `RealWriterPackagedBrowserBridge` in
`tests.acceptance.test_explorer_db_detail_browser_diagnostic`, enabled with
`RUN_EXPLORER_DB_DETAIL_BROWSER_DIAGNOSTIC=1` under the external supervisor and
`EXPLORER_BROWSER_SUPERVISED=1`. A skip, unavailable Chromium/WebGL or containment
failure is not acceptance. One successful after-graph-ready selection does not
establish real fault/race/contention evidence, representative 5k/20k latency,
responsive loading, useful/smooth focus or completion of issue #70. No speed
threshold or optimization is selected by this bridge. Keep #70 open.

Owned writer samples additionally retain a route-allowlisted graph/search/POST/
detail request inventory, status and fetch-to-headers elapsed, sanitized partial
failure labels and a boolean browser-route fault-injection label. Unknown routes
and caller-supplied URLs are not published. Renderer context uses only fixed
`webgl1`/`webgl2`, WebKit/unclassified vendor/renderer and software-SwiftShader/
software-other/unclassified implementation classes; raw unmasked device strings
are not retained. If supplied, `graph_matches_fixture` must be true for success.
Writer metadata bounds are checked (12–20,000 tracks, unsigned32-bit seed,
1–3 history rows); the full owned manifest remains the collection boundary's
provenance rather than arbitrary supplied fields.

Writer-only `--sample-profile warm` performs an explicit startup-graph-ready
warmup using the same browser/page before the observed navigation. The report
labels warmup completion and leaves disk-cache state `not_established`; this is
not disk-warm or a 5-process/20-warm comparative campaign. Separately observed
server requests include warmup and are labeled accordingly. Generated 5k/20k
single-sample runs require separate parent-approved fixture/resource envelopes;
they do not imply representative latency distributions or issue acceptance.

Writer server telemetry is bounded: repeated evidence preflight/fetch/decode/
payload leaf spans are capped at 16 per phase/request. This limits observation
retention only, not reader execution or trust validation. Omitted-span and
failure counters are explicit; sampled report/phase status is not a full
microprofile. Inclusive parent timing may remain observed, but all exclusive
phase durations are unavailable/null when spans were omitted—do not infer full
exclusive attribution. A report-size resource failure before this cap is retained
as failed external evidence, not relabeled a successful pre-cap run; RAM, swap,
per-file and scratch limits are not increased. `graph_fault_injected` separately
labels whether the graph fault callback actually ran; choosing a scenario alone
does not certify an injected fault.

Writer-only failure probes remain separate from browser-only lifecycle scenarios:
`--scenario rejected-post` injects one browser-route HTTP409 response to current
POST; the attempt is `invalid_response`, with no accepted detail success.
`--scenario detail-timeout` aborts one actual detail GET at the browser route,
then the bounded observer wait expires; the attempt is `timeout`, retaining the
accepted POST and partial GET request observations. This is an injected browser
network failure and observer timeout, **not an observed packaged-server timeout**.
The supervised tiny runs executed these probes as expected failed attempts, not
speed evidence. The route callback invocation must be observed; choosing a
scenario alone never proves fault injection. Neither probe is counted as a
successful detail-latency sample.

Writer `--wait-timeout-ms` defaults to 10,000 and is explicitly bounded to
10,000–120,000 milliseconds. It is a browser operation/warmup safety wait,
reported as `safety_wait_timeout_ms`, not a performance target or permission to
increase RAM/scratch/file limits. A larger explicit wait may be necessary for
bounded generated profiles; the independent external hard-wall deadline remains
mandatory and authoritative. Retain expired waits as failed attempts with their
partial evidence, never as skipped acceptance.

The approved generated-profile campaign uses separate owned, isolated tmpfs
mounts: 1 GiB aggregate fixture scratch with a 512 MiB per-database-file ceiling,
and 128 MiB aggregate browser scratch with 32 MiB per file. No overlay fallback
or automatic cap increase is permitted. The external supervisor sets inherited
RLIMIT_FSIZE to 512 MiB during fixture construction and resets it to 32 MiB
before browser launch; observed samples remain read-only and do not write the
database. The CLI does not manage mounts. The supervisor kills/reaps tracked
children, verifies zero survivors, and removes owned scratch roots after
namespace/mount teardown. Any other profile/envelope needs separate approval.
Installed-wheel campaign namespaces verify packaged runtime files against the
exact base; this provenance is distinct from source-checkout contract tests.
Expired 10-second waits (including partially observed accepted POST bodies) are
retained as failed/partial evidence. An explicit 60-second safety wait within an
independent 900-second hard wall changes neither resource caps nor latency
acceptance budgets, and must not relabel a prior timed-out run as successful.
