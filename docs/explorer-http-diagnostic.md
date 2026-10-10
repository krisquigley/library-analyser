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
client request/response, not isolated server phases. These are **observer-on HTTP
wall times**: the SQL observer synchronously runs EXPLAIN and records operations
**inside the timed requests**. They are not an uninstrumented baseline; neither
observer overhead nor individual server phases can be inferred from them.
Validation, membership, selected SQL, stage parse, mapping and serialization are
explicitly unavailable
unless independently instrumented; SQL EXPLAIN is not timing attribution.

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
