# Public HTTP selection/detail diagnostic (issue #70, PR4c)

This developer-only outward tool owns a new writer-generated schema-v10 fixture
and an ephemeral `127.0.0.1` HTTP server. It accepts no database path, audio,
private catalogue, remote URL, host or port. Packaged Explorer behavior is not
changed. `POST /api/current` changes disposable server session state, not SQLite.

From the repository root, a tiny report can be obtained with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import json
from tools.explorer_http_diagnostic import run_public_http_diagnostic
print(json.dumps(run_public_http_diagnostic(), sort_keys=True, allow_nan=False))
PY
```

Defaults are 12 tracks, seed 70, two history generations, one sample. Requests
are state, nonblank bounded summary search, current selection, then selected
track detail only after an accepted POST. Detail must be an object whose handle
matches the selection. The built-in loopback HTTP transport explicitly disables
proxy discovery: environment proxy settings cannot redirect these diagnostic
requests through a proxy. Its explicit HTTP-only handler set does not initialize
an unused HTTPS context or trust store inside the request deadline; other URL
schemes are unsupported. Redirects are not followed; 3xx responses are failed
observations, not hidden request hops. Body stalls and truncated responses retain
known status, received partial-byte counts and elapsed time as failed attempts.
Errors and timeouts remain samples; failed response bodies, exceptions,
scratch paths and selection handles are not
published. Fixture construction and graph manifest construction are outside
request timings; there is no graph HTTP request.

`sample_count` is an exact integer 1–100. `timeout_seconds` is finite, positive,
and at most 60 seconds per request. This is one absolute monotonic deadline
shared by connection establishment, request sending, response headers and body
(including HTTP error bodies), not a socket inactivity allowance renewed by
arriving bytes. A finite trickle still times out; known status, partial entity
bytes and elapsed time remain failure evidence, excluded from successful p95.
The built-in numeric loopback URL requires no remote DNS resolution.
More than 12 tracks requires explicit
`allow_large=True`; writer fixture bounds remain 12–20,000 tracks, unsigned
32-bit seed, and 1–3 history generations. Fixture and server lifecycle cleanup
runs on startup failure, HTTP rejection, timeout and ordinary completion.
The built-in factories guarantee the disposable public fixture and loopback-only
ephemeral binding. Injected factories are **trusted** diagnostic/testing
collaborators, not sandboxed inputs or public private-target CLI inputs. They
must honor that same contract: a newly owned disposable public-only fixture and
a server bound to `127.0.0.1` on an ephemeral port, with compatible cleanup.
Arbitrary injected Python code is not checked for compliance; do not use it
against a nonpublic catalogue.

Reports preserve caller-supplied warm and process-cold profiles separately in
`publish_http_report`; the live in-process runner labels its samples warm, not
disk-cold. Successful durations use nearest-rank p50/p95/max; failures never
enter successful percentiles. An empty/all-failed profile has null percentiles.
Intervals are validated using the original clock/flow identities before labels
are sanitized, retaining invalid-order errors. HTTP durations measure the
client request/response, not isolated server phases. The warm attempt denominator
includes state, summary, accepted selection POST and detail GET; it is not a
browser click-to-visible-detail interval.

`server_observation` publishes request-local monotonic spans collected by
process-local outward wrappers, not changes to packaged behavior. Historical
evidence subphases retain bounded size preflight, actual chunk execute/cursor
fetch, JSON decode and original payload validation separately. Fetch spans cover
cursor work, not processing performed by the iterator's caller; these are
observations of the existing fail-closed checks, not copied or relaxed policies.
Validation and its schema/rows/graph/historical-evidence children, membership, selected read,
stage preflight/decode, mapping, DTO serialization, UTF8 encoding and socket
write remain separate phases. DTO serialization records adapter conversion and
JSON encoding as separate spans with the same phase label; neither is hidden
inside mapping or UTF8 encoding. The inclusive request root wraps the actual
handler GET/POST call. Selected SQL execution and actual cursor draining
are distinct; EXPLAIN itself is not execution/fetch attribution. The SQL
operation allowlist covers `summary_count`, `summary_page`, `selected_track`,
`selected_locations`, `selected_latest_run`, `selected_stage_sizes`,
`selected_stage_payload`, `selected_overrides`, `selected_metadata` and
`selected_audio`, including actual bindings and same-connection query plans.
It does not claim per-SQL attribution for every validation query; historical
validation is observed through the separately named subphases. Socket-write
completion is **not client receipt or browser presentation**. Completed and failed
spans survive failed attempts. Missing phases are unavailable with null duration,
not zero; an observed zero-duration span is still a measurement. Nonfinite,
reversed or wrong-clock durations are flagged and published as null.

Correlation identities are replaced with opaque public IDs only after grouping
by original request/thread/span identity. Parent-exclusive time subtracts the
union of same-request, same-thread child intervals, never overlapping child sums.
Invalid or incomplete children make exclusive time unavailable. Cyclic parent
links are flagged `invalid_hierarchy` with unavailable exclusive time. Partial
cursor-drain records retain observed elapsed work and `partial` status; a
finite interval alone does not certify a fully consumed cursor. Both raw SQLite
records and correlated server iteration spans preserve `partial` until the
consumer requests exhaustion; only then are their iteration statuses completed.
A successful `fetchone` or `fetchmany` call does not by itself assert that the
caller exhausted the cursor. No nested or
parallel spans are summed as a sequential wall-clock total. A repeated phase has
its individual spans and sample count, but no single additive phase duration.
HTTP client intervals and server spans are different scopes; do not subtract
unrelated clocks or join them into a fabricated end-to-end waterfall.

Observer-on HTTP wall times include synchronous SQL EXPLAIN, wrapper timing and
recording overhead **inside timed requests**. `observer_explain` separately
measures actual same-connection EXPLAIN execute and fetchall, excluded from
selected SQL execute/fetch spans but included in enclosing request scopes. It
measures one observer cost, not total instrumentation overhead: wrapper, timer
and publication costs are not collectively isolated. The profiler does not
estimate or subtract this perturbation; paired on/off wall-time differences
remain confounded by cache state and run order. Observer-off runs publish no server measurements;
paired on/off observations require matching source, fixture and declared sample
counts and retain all failures. Neither a tiny contract pass nor these observer
labels establish responsiveness, a latency budget or a selected index benefit.

SQLite provenance records actual bound SQL and same-connection EXPLAIN rows,
including repository metadata UDFs, SQLite version and existing index DDL.
Read-only main/WAL SHA-256 values are compared before and after server use.
Absent WAL is null. Context is caller-owned-quiescent, **not** an atomic snapshot
of a concurrently changing live database. No immutable connection, checkpoint,
ANALYZE, migration, new index or reader validation bypass is introduced.
Full validation still rejects unrelated corrupt historical evidence. The SQL
observer temporarily wraps the repository connection boundary process-wide;
use one owned diagnostic lifecycle at a time, without unrelated concurrent
reader activity or overlapping diagnostic runs. The original boundary is
restored on context exit, including failures.

## Verification and safety

Default contracts do not build large fixtures:

```sh
ulimit -c 0
timeout --signal=KILL 180s env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
 tests.unit.benchmark_tools.test_explorer_http_absolute_deadline \
 tests.unit.benchmark_tools.test_explorer_http_deadline_budget \
 tests.unit.benchmark_tools.test_explorer_http_only_transport \
 tests.unit.benchmark_tools.test_explorer_http_diagnostic_proxy \
 tests.unit.benchmark_tools.test_explorer_http_diagnostic_report \
 tests.acceptance.test_explorer_http_diagnostic \
 tests.acceptance.test_explorer_http_trickle_cleanup \
 tests.integration.infrastructure.test_explorer_http_diagnostic_provenance
```

The explicit expensive integrity contract builds deterministic 5k/20k fixtures
in fresh subprocesses; each profile has a 900-second bound and process-group
SIGKILL/reap on timeout. A parent-owned temporary directory is exported through
TMPDIR/TEMP/TMP and removed even when the child is killed. Run only in an
externally resource-bounded environment with adequate scratch space:

```sh
timeout --signal=KILL 1900s env RUN_EXPLORER_HTTP_DIAGNOSTIC_LARGE=1 \
 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
 tests.integration.infrastructure.test_explorer_http_diagnostic_provenance
```

The test itself does not enforce an aggregate scratch or RAM limit. Record
actual external limits and all failures; a skipped opt-in test is not evidence
of a completed large profile. A 1 GiB aggregate scratch cap can be insufficient
when main and WAL coexist. Do not silently enlarge limits or weaken tests.
Full-suite verification belongs to CI; targeted local contracts are diagnostic
integrity checks, not a performance budget.

Scope is public-synthetic-http-only. Browser parse/render/paint, real ~41 MB
payloads, camera/selection semantics, and responsiveness/performance claims are
separate PR4d work. This report asserts no latency budget or universal speed.
