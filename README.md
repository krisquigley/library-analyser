# Local Music Analyser

A local, privacy-preserving toolkit for understanding a personal music library.
It catalogues audio files you explicitly select, runs audio analysis (tempo, key,
and provisional genre/mood/instrument/energy scores from pretrained Essentia
models), stores the evidence in a dedicated SQLite database, and lets you review,
annotate, export and visually explore it.

**Why:** DJ and listening tools need trustworthy track metadata, but tags are often
missing or wrong. This project keeps the raw evidence (scores, coverage,
uncertainty and provenance) instead of inventing confident tags, so a human can
review it before relying on it.

## Status and boundaries

This is **experimental** software, delivered in small tested increments.

- Everything runs **locally**. Your music, paths and results are not uploaded.
  Only the explicit `models download` command uses the network.
- It never edits audio files or their tags. It writes only its own analysis
  database, model bundles, an embedding cache, temporary decode snapshots
  (removed after use) and the export/projection files you name.
- There is **no Mixxx integration** yet, and it must never be pointed at a Mixxx database.
- Model scores are **not calibrated** probabilities or confirmed tags. Real
  inference has only been validated on one pinned runtime in a
  [bounded 14-track pilot](docs/real-pilot.md); listening/accuracy evaluation is open.
- Essentia model licensing has a publisher discrepancy (non-commercial terms); see
  [Model setup](docs/analyzer-reference.md#model-setup-integrity-not-inference).

## Two packages, one distribution

The `music-analyzer` distribution (Python **3.11+**) installs two packages and
their command-line entry points:

| Package | Command | What it does |
| --- | --- | --- |
| `music_analyzer` | `music-analyzer` | Catalogue, analysis and review CLI: `doctor`, `models`, `scan`, `analyze`, `status`, `list`, `show`, `override`, `reaggregate`, `export`, `graph`, `integrity`, `prepare-projection`. It **writes** the analysis database. |
| `music_explorer` | `music-explorer` | Read-only localhost web explorer of an existing analysis database: search, track detail, a 3D mood-axis graph, candidate suggestions and M3U playlist export. It **never writes** the database. |

`music-analyzer explorer` is a compatibility route to the same explorer, and
`music-exporer` is a retained misspelled alias of `music-explorer`. The explorer
depends only on the database the analyzer produces, so the flow is:
**analyzer writes → explorer reads**.

## Install

```sh
python -m venv .venv
. .venv/bin/activate                   # later commands assume the venv is active
python -m pip install .
music-analyzer doctor                  # what is available on this machine
```

The only default runtime dependency is `mutagen` (duration and embedded tag metadata). Cataloguing,
review, export, graph building and the explorer need nothing else. **Audio
analysis** additionally needs FFmpeg on `PATH` plus an Essentia TensorFlow
runtime that is *not* installed by default. The tested combination and its caveats
are in the [real-pilot report](docs/real-pilot.md). `doctor` reports what is
missing but never installs anything, and its exit 0 does not mean analysis is ready.

## Quick start

All commands accept `--database PATH`. The default is
`$XDG_DATA_HOME/music-analyzer/analysis.sqlite`, and its parent directory must
already exist. Configuration precedence is CLI > TOML > defaults; see
[Configuration](docs/analyzer-reference.md#configuration-and-overrides).

```sh
DB=/path/to/existing/dir/analysis.sqlite

# 1. Download and verify the six pinned model bundles (network; ~30 MiB).
music-analyzer models download
music-analyzer models verify

# 2. Inventory an explicitly selected folder. This records files, sizes, mtimes,
#    content hashes, durations and embedded tags; it does NOT analyze audio.
music-analyzer scan /path/to/selected/music --database "$DB" --json

# 3. Analyze. Batch mode works through eligible catalogue tracks with one worker;
#    --limit caps attempts. Requires FFmpeg and the Essentia runtime.
music-analyzer analyze --database "$DB" --limit 10
music-analyzer status --database "$DB"

# 4. Review stored evidence (no inference) and add manual annotations.
music-analyzer --database "$DB" list --needs-review
music-analyzer --database "$DB" show TRACK_ID
music-analyzer --database "$DB" override set TRACK_ID bpm '123.5'
music-analyzer --database "$DB" export --format csv --output /path/to/new-review.csv

# 5. Build the persisted related-track graph, then explore it in a browser.
music-analyzer graph build --database "$DB"
music-explorer --database "$DB" --port 8765    # open http://127.0.0.1:8765/
```

Scanning is not analysis. A track appears with results only after a completed
analysis run, and `list --needs-review` is intentionally conservative. Exports
refuse to overwrite existing files.

The explorer binds only to `127.0.0.1` and reads the database in read-only SQLite
mode. Each request checks only the rows it reads. For an explicit full audit of a
database, especially an old, copied or restored one, run the offline diagnostic:

```sh
music-analyzer integrity --database "$DB" --json
```

## Documentation

- [CLI and Explorer reference](docs/analyzer-reference.md): every command, its
  limits, exit codes and safety boundaries (models, scan, batch analysis,
  embedding cache, review/export, explorer and projection artifacts).
- [Integrity diagnostic (D3)](docs/integrity.md) and the
  [Explorer read policy](docs/explorer-read-policy.md).
- [Real-runtime pilot](docs/real-pilot.md): the tested inference environment and
  its limits.
- Explorer internals and measurement tooling:
  [startup contract](docs/explorer-startup-performance.md),
  [selection camera](docs/explorer-selection-camera.md),
  [public fixture](docs/explorer-public-fixture.md),
  [HTTP](docs/explorer-http-diagnostic.md) and
  [browser](docs/explorer-browser-diagnostic.md) diagnostics,
  [interaction measurement](docs/explorer-interaction-measurement.md),
  [graph-read benchmark](docs/graph-read-benchmark.md), and the track-journey
  [phase 2 policy](docs/track-journey-explorer-phase2-policy.md) and
  [phase 3 projection artifacts](docs/track-journey-explorer-phase3-projection-artifacts.md).
- Planning: [track journey explorer plan](plans/track-journey-explorer-plan.md).

## Contributing

Issues and pull requests are welcome at
<https://github.com/krisquigley/library-analyser>. Please read
[AGENTS.md](AGENTS.md), which holds the project rules for humans and coding agents alike.

**Architecture.** Both packages follow Clean Architecture. Source dependencies point inward:

```text
<package>/
  domain/               business rules: pure, no I/O or frameworks
  application/          use cases, ports (interfaces), DTOs
  interface_adapters/   presenters, controllers, mappers
  infrastructure/       SQLite, FFmpeg, Essentia, filesystem, HTTP clients
  frameworks/           CLI entry points, web server, composition root
tests/{unit,integration,acceptance,architecture}
tools/                  public-safe diagnostics and benchmarks (not shipped)
```

Domain and application code must not import infrastructure or framework code.
`tests/architecture` enforces this with AST import checks. Concrete adapters are
wired only in `frameworks/`.

**Workflow.** Development is test-driven: write a failing test (red), make it pass
(green), then refactor. Bug fixes start with a regression test that reproduces the
bug. Use synthetic or generated fixtures only; never commit private library paths,
titles, databases or audio.

**Checks** (standard-library `unittest`, run from the repository root):

```sh
python -m unittest discover -s tests/unit -t . -v              # fast unit tests
python -m unittest tests.architecture.test_import_boundaries -v
RUN_FFMPEG_TESTS=0 RUN_PACKAGING_TESTS=0 python -m unittest discover -v   # full suite, as CI
RUN_FFMPEG_TESTS=1 python -m unittest tests.integration.infrastructure.test_audio_decode -v
```

Two packaging tests need extra setup:
- `tests.acceptance.test_music_explorer_packaging_and_compat` always builds a wheel
  with `pip wheel`, which fetches `setuptools>=77` from your package index.
- `tests.acceptance.test_integrity_d1_installed` installs offline from a
  `setuptools>=77` wheel in `/usr/share/python-wheels` (Debian/Ubuntu layout).
  `RUN_PACKAGING_TESTS=0` skips it.

FFmpeg decode (`RUN_FFMPEG_TESTS=1`) and Playwright/Chromium browser tests
(`RUN_BROWSER_SMOKE=1`) are opt-in. The formal browser gate runs every browser
module against the installed wheel under a Podman supervisor; see
[Explorer browser gate](docs/explorer-browser-gate.md). CI (`.github/workflows/ci.yml`) runs on
ubuntu-24.04 with Python 3.14.8.

**Proposing changes.** Open an issue describing the problem and the expected
behavior. Branch from `main`, keep pull requests focused, say which tests you ran,
and document any architectural trade-off in the pull request description.
