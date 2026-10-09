# Public Explorer measurement contracts (issue #70, PR4a)

This is a reusable **contract library**, not the planned PR4 end-to-end synthetic
diagnostic harness. It does not start a server or browser, issue requests, select
a track, instrument production code, or measure latency by itself. Use it only
with public synthetic observations and test-owned SQLite fixtures. Product
behavior, schema, indexes, and validation trust are unchanged.

## Public APIs

Import the six functions from `tools.explorer_interaction_measurement` in a
repository checkout with Python 3.11+. The library has no command-line runner.

- `summarize_interactions(attempts)` retains supplied attempts, including
  failures. Profiles (for example `process-cold` and `warm`) are summarized
  separately. Only successful durations contribute to nearest-rank p50/p95/max;
  all-failed profiles have null quantiles, not fabricated zeros. Process-cold is
  a caller-supplied label, not proof of disk-cold caches. Small sample counts are
  not statistically robust. Samples are supplied observations, not generated
  measurements, and are not automatically scrubbed of private data.
- `validate_phase_intervals(intervals)` checks finite, non-reversed,
  non-overlapping **sequential** phases in supplied order within each
  `(clock, flow)`. Different clock origins and concurrent graph/detail flows
  remain independent. This is not a nested-span validator, instrumentation, or
  cross-clock synchronization mechanism.
- `request_inventory(requests)` aggregates observed methods and sanitized route
  categories in deterministic order. It strips hosts, queries and track handles
  and redacts unknown routes. It makes no network calls; supplying a `POST`
  observation does not execute it.
- `graph_manifest(body, source='browser-only')` (with the explicit required source
  keyword) records actual UTF-8 entity bytes,
  SHA256 and counts of the `nodes`, `links`, and `unpositioned` arrays, and
  explicitly labels provenance. Only `browser-only` source is supported. Array
  checks do not validate the indexed-v3 envelope, row shapes or references. It is a
  descriptive manifest, **not an independent expected hash/count oracle**. A
  browser-only response cannot imply a SQLite schema or server query speed.
  Existing `tools.graph_read_benchmark.measure_samples` checks response integrity
  against an independently established oracle; a manifest from the same response
  must not be passed off as such an oracle.
- `inspect_fixture(path)` inspects a prepared synthetic writer-owned SQLite
  fixture through a read-only, query-only connection and closes it on success
  or failure. It reports schema/application IDs, integrity/FK results and bounded
  aggregate counts. It does not migrate, create indexes, run ANALYZE, or certify
  complete repository schema/evidence trust. Missing inputs are not created;
  invalid fixtures produce a generic error rather than exposing database text.
  SQLite may maintain SHM coordination state while reading a live WAL; inspection
  is therefore restricted to disposable caller-owned synthetic fixtures, not an
  immutable/no-filesystem-change guarantee for live data.
- `fingerprint_sqlite_files(path)` reads the main file and optional WAL using
  streaming SHA256. Missing WAL is explicitly null. Main and WAL hashes are
  **sequential, not an atomic snapshot**: use test-owned quiescent fixtures, not
  this comparison as an unchanged guarantee for a live library. Checkpoint races
  can yield inconsistent comparisons. The filesystem APIs live in the separate
  outward `tools.explorer_fixture_inspection` module and are reexported for the
  public seam; pure report functions perform no filesystem/SQLite operations.

### Small report example (supplied observations only)

```python
from tools.explorer_interaction_measurement import summarize_interactions

report = summarize_interactions([
    {'sample': 0, 'profile': 'warm', 'outcome': 'ok', 'elapsed_ms': 12},
    {'sample': 1, 'profile': 'warm', 'outcome': 'timeout', 'elapsed_ms': None},
])
assert report['attempted'] == 2
assert report['profiles']['warm']['succeeded'] == 1
assert report['profiles']['warm']['failures'] == {'timeout': 1}
```

The `12` above is example input, **not a benchmark result**. Callers own collection,
timeouts/resource limits, public-data provenance, fixture preparation, and cleanup.
Keep generated files in a `TemporaryDirectory` and close connections before
cleanup, including on exceptions. This library does not promise hard execution
time limits or manage an external browser/server lifecycle.

## Verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.unit.benchmark_tools.test_explorer_interaction_measurement \
  tests.unit.benchmark_tools.test_explorer_interaction_measurement_robustness \
  tests.unit.benchmark_tools.test_explorer_fixture_inspection
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.architecture.test_import_boundaries \
  tests.architecture.test_music_explorer_boundaries
git diff --check
```

The supplied regression tests use a one-track writer-generated v10 fixture and a
less-than-4-KiB valid indexed-v3 browser-only body. They cover contracts and cleanup,
not representative rich v10 graph performance. The existing startup tests use
synthetic 5k/20k v6 summary fixtures; those are not a substitute for v10 evidence
coverage. Browser tests skipped without opt-in/dependencies are **not** browser
acceptance evidence.

## Architectural boundary

These are outer measurement-tool observations, not domain or application
business rules. The public tools module is a composition facade: pure report
functions perform no I/O, fixture details are separated, and the existing
nearest-rank helper is reused. No production inner layer imports tools. If future
report policy becomes an application use case, move those pure rules inward and
provide explicit ports rather than importing this tools facade into application
or domain code.

## Explicitly deferred to PR4b and subsequent diagnostic delivery

- Reproducible rich v10 5k/20k generator, active/excluded/unavailable populations,
  stage/history distributions, positioned graph data and DB-backed graph oracle.
- Independently verified ~41 MiB-class browser-only graph fixture, separately
  labeled from actual database-backed output.
- Actual HTTP transport and database phase attribution, bound SQL EXPLAIN plans,
  hardware/runtime/cache manifests and repeated process-cold/warm samples.
- Real-browser milestones, long tasks/frame gaps/input latency, usable rendered
  graph, detail-painted and focus/halo observations, with timeout/failure cleanup.
- A genuinely runnable opt-in diagnostic tool, red-tested before implementation.

No full PR4 completion, ~41 MiB end-to-end speed, or issue #70 completion is
claimed. Synthetic integrity is not server/browser latency. No private databases,
user paths, live POSTs, or schema/index changes are required or authorized here.
Container operations, if needed for future work, must use Podman, not Docker.
