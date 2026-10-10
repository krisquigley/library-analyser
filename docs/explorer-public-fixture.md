# Public synthetic current-schema Explorer fixture

`tools.explorer_synthetic_fixture.public_synthetic_fixture` is an outward,
Python context-manager API for disposable public SQLite integrity fixtures.
It is not a timing harness, HTTP server runner, browser runner or CLI. It accepts
no database, audio, path or metadata input and never reads a private catalogue.
Fixture construction belongs outside request timing.

## API and lifecycle

```python
import json
from tools.explorer_synthetic_fixture import public_synthetic_fixture

with public_synthetic_fixture() as fixture:
    # Use this caller-owned disposable path only within the context.
    db_path = fixture['db_path']
    manifest = fixture['manifest']
    graph_body = fixture['graph_body']  # canonical indexed-v3 JSON bytes
    print(json.dumps(manifest, sort_keys=True))
```

The signature is
`public_synthetic_fixture(track_count=12, seed=70, history_count=2, allow_large=False)`.
Options are strictly typed: booleans are not accepted as integers.

- `track_count`: integer from 12 through 20000. Any value above 12 requires
  `allow_large=True`, including a small 24-track profile.
- `seed`: integer from 0 through `2**32 - 1`.
- `history_count`: integer from 1 through 3; controls completed runs per track
  and retained graph snapshots.
- `allow_large`: a boolean acknowledgment, not an automatic resource limiter.

Invalid types/ranges raise `ValueError('Invalid public synthetic fixture options')`;
a larger profile without opt-in raises
`ValueError('Large synthetic fixture requires explicit opt-in')` before allocation.
Use external process, time, memory and scratch-disk bounds for expensive work.

Each context owns a fresh temporary root. The root, main database and any
sidecars are removed on normal exit or consumer exception; consumer exceptions
propagate. The path is invalid after exit. Fixtures are quiescent when yielded;
reader/inspection and ordinary current-schema writer reopen checks preserve the
main/WAL fingerprint. Sequential file hashes are not an atomic live-WAL snapshot;
SHM coordination state is not a committed-data fingerprint.

## Writer ownership and public content

The ordinary `SQLiteAnalysisRepository` initializes the exact writer-owned v10
schema (`application_id=0x4D414E41`, `user_version=10`). No custom DDL, indexes,
migrations or production reader policies are introduced. Synthetic population
reuses public stage, duration and graph-feature-evidence contracts; graph
promotion uses the writer's public `replace_graph_snapshot` API. The actual
read-only Explorer repository, `BuildMoodAxisGraph` use case and indexed-v3 HTTP
mapper produce `graph_body`; it is not fabricated browser-only graph data.

Architectural tradeoff: this outer diagnostic tool bulk-inserts fixture rows in
its own foreign-key-enforced transaction instead of replaying audio-analysis
workflows. It also normalizes fixture-owned operational graph IDs/timestamps,
including foreign-key references, to deterministic public values. This SQL is
fixture-only detail, not an application persistence API. Dependencies point
inward from tools to existing contracts; no inner layer imports the tool.

Each twelve-track block contains one excluded track, one eligible unpositioned
track and two unavailable eligible positioned tracks. Availability and
eligibility remain distinct under the existing reader policy. Partial blocks
follow the same slot pattern. Metadata includes duplicate titles, Unicode and
literal punctuation. Every completed run has five bounded stages, including
score windows/summaries and provenance. Eligible tracks have valid linked
current/historical graph feature evidence. Graph snapshots use chains over all
eligible tracks and separately over positioned tracks, not an expensive
all-pairs topology.

The default literal oracle is:

| Aggregate | Count |
| --- | ---: |
| Tracks / eligible / excluded / unavailable | 12 / 11 / 1 / 2 |
| Locations / active locations | 12 / 9 |
| Completed runs / stages | 24 / 120 |
| Current / historical feature evidence | 11 / 11 |
| Retained / current graph builds | 2 / 1 |
| Current eligible / positioned edges | 10 / 9 |
| Retained eligible / positioned edges | 20 / 18 |
| Indexed graph nodes / links / unpositioned | 10 / 9 / 1 |

## Canonical manifest, not physical database identity

The manifest contains only fixed public provenance, schema identifiers, seed,
profile sizes, integer aggregate counts/distributions and graph integrity data.
It contains no temporary path, handles, metadata or evidence bodies.

- `source` is `public-synthetic-sqlite`; `graph.source` is `sqlite-backed`.
- `graph.sha256` hashes actual `graph_body`; `graph.body_bytes` is its UTF-8
  entity length; graph counts describe nodes, links and unpositioned entries.
- `content_sha256` hashes the manifest without its own digest, encoded with
  `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False,
  allow_nan=False).encode('utf-8')`.

The same seed/profile yields identical manifest and graph bytes at different
temporary paths. A changed seed changes actual content. Neither digest promises
identical SQLite page layout, a raw DB-file hash or performance. The manifest
is not a complete runtime/hardware/cache/browser measurement manifest.

## Integrity checks

From the repository root with project Python dependencies installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.unit.benchmark_tools.test_explorer_synthetic_writer_schema_red \
  tests.unit.benchmark_tools.test_explorer_public_fixture_manifest_red
```

The retained `_red` names identify the original unchanged TDD contracts, not
expected failures after implementation. Only tiny fixtures run by default;
the 5k/20k integrity method skips unless explicitly enabled:

```sh
RUN_EXPLORER_PUBLIC_FIXTURE_LARGE=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest -v \
  tests.unit.benchmark_tools.test_explorer_public_fixture_manifest_red.PublicFixtureManifestRedTests.test_opt_in_5k_and_20k_profiles_are_isolated_and_bounded
```

That method runs each profile in a subprocess with a 300-second bound and an
owned scratch directory. These commands do not themselves impose memory/disk
limits: use an external containment wrapper for expensive profiles. A skipped
large-profile test is not 5k/20k acceptance evidence. Successful integrity tests
are not host-independent latency assertions.

## Delivered and deferred

This PR4b slice supplies rich current-schema fixtures, aggregate manifests and
actual database-backed graph integrity. It does not supply independently
verified ~41 MiB browser-only graph generation, HTTP transport/SQL phase
attribution, bound EXPLAIN plans, hardware/cache manifests, repeated cold/warm
samples, browser milestones, detail-painted/focus/halo observations or a runnable
end-to-end diagnostic CLI. See [interaction measurement contracts](explorer-interaction-measurement.md).
No full PR4 delivery, issue #70 completion or server/browser speed claim is made.
No private database/audio, live POST, schema/index change or product-behavior
change is required or authorized. Container operations must use Podman.
