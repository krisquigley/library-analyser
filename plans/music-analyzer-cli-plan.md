# Local Music Analyser — CLI Implementation Plan

## Goal

Build a local command-line tool to analyse approximately 3,000 FLAC, MP3 and M4A files for BPM, key, mood, energy, genres and instruments. Save reviewable results and subsequently apply selected updates to Mixxx.

Target environment: the user's Omarchy Quattro Linux installation. This phase delivers a CLI; a future Quickshell interface can reuse its backend. Audio remains local. Internet access is needed only for installing dependencies and downloading models.

This document is a plan, not an implemented or validated tool. Command names below describe the intended interface.

## Technical approach

Use Python for orchestration, FFmpeg for audio decoding, Essentia for music analysis and pretrained inference, and SQLite for persistent results. Structure the implementation using Clean Architecture: domain and application policy stay independent from CLI, SQLite, FFmpeg, Essentia, Mixxx and filesystem details. Treat analysis engines, persistence, model downloads and Mixxx database access as adapters behind application ports.

| Attribute   | Initial library/model                                       | Output                                                         |
| ----------- | ----------------------------------------------------------- | -------------------------------------------------------------- |
| BPM         | Essentia RhythmExtractor2013, multifeature                  | BPM, native confidence, beat positions and section consistency |
| Key         | Essentia KeyExtractor                                       | Key, major/minor scale, strength and section estimates         |
| Genres      | Discogs-EffNet embeddings + genre_discogs400-discogs-effnet | Ranked genre/style labels and raw model scores                 |
| Mood        | mtg_jamendo_moodtheme-discogs-effnet                        | Multiple mood/theme tags and scores                            |
| Instruments | mtg_jamendo_instrument-discogs-effnet                       | Instrument categories, scores and section presence             |
| Energy      | MSD-MusiCNN embeddings + emomusic-msd-musicnn               | Raw arousal/valence and provisional 0–100 energy score         |

Reuse compatible Discogs-EffNet embeddings across the genre, mood and instrument classifiers. The energy model uses a separate MusiCNN representation. Follow each model's metadata for preprocessing, sample rate, tensor names and class ordering.

Use pretrained weights initially. Benchmark alternatives only when the pilot identifies a concrete weakness. MTG models carry CC BY-NC-SA terms; retain their license and attribution information with the downloaded assets.

## Architecture and boundaries

Use Clean Architecture so the CLI remains a delivery mechanism over reusable application use cases. Dependencies point inward only:

```text
frameworks/cli
    ↓
interface_adapters
    ↓
application
    ↓
domain
```

The future Quickshell interface should be able to call the same application use cases without reusing CLI parsing or terminal output code. Mixxx support is also an outer adapter, not part of core analysis policy.

### Domain layer

The domain layer contains framework-free music analysis concepts and rules:

- track identity, audio file location and recording identity value objects;
- analysis stages, stage status, retry state and provenance entities;
- prediction, score, confidence, ambiguity flag, segment and summary value objects;
- rules for result invalidation, threshold interpretation, review status and manual override precedence;
- errors that describe domain conditions, such as unsupported audio, ambiguous tempo or stale change sets.

Domain code must not import SQLite, FFmpeg, Essentia, TensorFlow, command-line libraries, filesystem walkers, Mixxx schemas, logging frameworks or environment/config readers.

### Application layer

The application layer contains use cases and ports. Initial use cases should include:

- `RunDoctor` — validate configured dependencies through ports;
- `DownloadModels` and `VerifyModels` — coordinate model manifest, integrity checks and attribution recording;
- `ScanLibrary` — register files and detect changes;
- `AnalyzeTrack` and `AnalyzeBatch` — orchestrate decoding, inference, aggregation, checkpoints and retries;
- `ShowTrack`, `ListTracksForReview` and `ReportStatus` — query reviewable state;
- `ExportResults` — produce JSON/CSV-ready data;
- `InspectMixxxDatabase`, `PreviewMixxxChanges` and `ApplyMixxxChanges` — map verified analysis results to a guarded Mixxx change set.

Define ports in the application layer for filesystem traversal, metadata reading, audio decoding, rhythm/key analysis, embedding extraction, classifier inference, model storage, analysis persistence, transaction locking, Mixxx database access, clocks and output file writing. Use cases depend on these ports, never on concrete adapters.

### Interface adapters and infrastructure

Interface adapters translate between external formats and application/domain models: CLI controllers, presenters, CSV/JSON mappers, SQLite row mappers, Essentia result mappers and Mixxx schema mappers.

Infrastructure implements application ports using concrete tools: SQLite, FFmpeg, Essentia/TensorFlow, HTTPS downloads, XDG paths and filesystem access. Keep all external-library configuration and failure translation at this boundary.

Composition belongs at the outer edge. The CLI entry point wires concrete adapters to application use cases; application services do not construct SQLite connections, FFmpeg processes or model clients themselves.

## Proposed CLI

The working command name is `music-analyzer`.

```bash
# Check tools, inference support, models and configured paths
music-analyzer doctor

# Download the selected model versions and record their checksums
music-analyzer models download
music-analyzer models verify

# Register files without changing their tags
music-analyzer scan ~/Music

# Start with a representative sample, then process the remainder
music-analyzer analyze --limit 50
music-analyzer analyze

# Inspect progress, errors and individual results
music-analyzer status
music-analyzer show TRACK_ID
music-analyzer list --needs-review
music-analyzer analyze --retry-failed

# Reanalyse explicitly when desired
music-analyzer analyze --track TRACK_ID --force

# Export reviewable results
music-analyzer export --format csv --output analysis.csv
music-analyzer export --format json --output analysis.json

# Later: inspect and apply a concrete Mixxx change set
music-analyzer mixxx inspect --database /path/to/mixxx.sqlite
music-analyzer mixxx preview --database /path/to/mixxx.sqlite --output changes.json
music-analyzer mixxx apply --database /path/to/mixxx.sqlite --changes changes.json
```

Global options should support a configuration file, analysis database path and model directory. Analysis options should include worker count, selected tasks, sampling coverage and maximum track duration. Offer machine-readable JSON output alongside human-readable progress.

Ctrl+C stops dispatching new jobs and safely checkpoints progress. Repeating `analyze` resumes outstanding work. Reserve stdout for requested output and stderr for progress and diagnostics. Return non-zero exit codes for setup failures and batches containing failed tracks.

## Processing workflow

1. **Inventory files.** Walk configured roots, record paths, sizes and modification times, and read available metadata. Handle Unicode paths, inaccessible files and unsupported audio streams explicitly. Do not follow directory symlinks by default.
2. **Identify changes.** Use filesystem metadata for quick checks and content hashes for reliable result reuse. Hash-identical files may share analysis, but retain their separate locations for Mixxx mapping. Different encodings are not automatically treated as identical recordings.
3. **Decode audio.** Decode each track once, derive the sample rates required by the analysers and retain original levels for loudness measurements. Bound memory and temporary storage. Reject oversized input with an actionable message instead of silently truncating it.
4. **Analyse rhythm and harmony.** Run full-track BPM/key analysis and section checks. Retain ambiguity flags for half/double tempo, changing tempo, key changes and weak tonal evidence. A BPM estimate is separate from a validated DJ beat grid.
5. **Analyse semantic attributes.** Start with several distributed windows, approximately 30 seconds each where appropriate. Respect each model's native framing. Compare sampled and full-track coverage during the pilot; expand coverage when sections disagree.
6. **Aggregate results.** Preserve full scores and window timestamps. Use average scores and variation for genre/mood. Retain sustained presence and strong local evidence for instruments, so brief solos remain discoverable.
7. **Persist immediately.** Commit completed stages, errors and provenance. Cache embeddings to support new thresholds or compatible classifier heads without decoding the track again.
8. **Review and export.** Display proposed labels separately from raw scores. Preserve manual overrides across future analysis runs.

## Interpreting results

- Treat model outputs as scores, not calibrated probability-of-correctness percentages.
- Support multiple genre, mood and instrument labels; allow uncertain or empty results.
- Begin with configurable provisional thresholds, then tune them on the pilot collection.
- Define energy as perceived intensity for choosing tracks. Initially map arousal to a display score and label it provisional. Keep raw arousal and valence; use user-rated examples to calibrate any later composite score.
- Retain loudness and rhythmic features separately rather than assuming loudness or BPM equals energy.
- Instrument labels are limited to the model vocabulary. Do not invent specific instruments the model cannot identify.
- Key output assumes a major/minor system; weak or unsuitable material should be flagged for review.

## Persistence and configuration

Use a dedicated `analysis.sqlite`. Reject unrelated database schemas if supplied as the analysis database; it must never accidentally initialise tables in `mixxx.sqlite`.

Suggested records:

| Record                     | Purpose                                                      |
| -------------------------- | ------------------------------------------------------------ |
| Tracks and locations       | File identity, paths and source metadata                     |
| Jobs and stage results     | Pending/running/completed/failed state and restart recovery  |
| Segments and predictions   | Window timestamps, model scores and coverage                 |
| Summaries and overrides    | Derived tags and preserved user corrections                  |
| Model versions and runs    | Model hashes, preprocessing settings and dependency versions |
| Export batches and changes | Proposed/applied Mixxx values and audit history              |

Use schema migrations, one database writer and an exclusive batch lock. Recover interrupted stages on restart. Isolate per-track failures and bound retries.

Store configuration under XDG config, durable results and model weights under XDG data, and reproducible temporary files/embeddings under XDG cache. Document cache limits and cleanup. Do not retain decoded copies of the entire music library.

Invalidate results when their relevant inputs change: audio identity, model hash, preprocessing or algorithm version. A display threshold change should rerun aggregation, not inference.

## Model setup and resource management

- Provide a model manifest with official URLs, versions, label metadata and license references.
- Download through HTTPS to temporary files and rename only after completion and validation.
- Record SHA-256 checksums. Distinguish locally recorded integrity checks from publisher-authenticated checksums; do not claim stronger verification than supplied.
- Make analysis work offline once dependencies and models are installed.
- Begin with one worker and bounded inference threads. Load models once per worker.
- Increase worker count only after measuring memory and throughput. GPU support is optional.
- Isolate the Python environment from Omarchy's system Python. Select and pin a tested interpreter/dependency combination after checking Essentia TensorFlow package availability.

## Mixxx integration — separate milestone

Implement after inspecting the user's actual Mixxx version and database schema.

1. Open the database read-only for inspection and map verified track identities to existing records.
2. Establish supported destinations for all six attributes. Do not assume dedicated mood, energy or instrument columns exist. Keep richer results in the analysis database.
3. Inspect how BPM/key fields relate to Mixxx's stored analysis data before choosing a write strategy. Preserve cue points, beat grids, playlists and unrelated metadata.
4. Generate a preview containing record identity, field, expected old value and proposed new value. Default to filling missing values; existing values require an explicit replacement policy.
5. Require Mixxx to be closed for application. Create a consistent SQLite backup using SQLite's backup mechanism so WAL state is handled correctly.
6. Recheck database identity/schema and expected values before applying the preview. Reject stale changes.
7. Apply an entire selected batch transactionally and record before/after values.
8. Verify a test copy reopens correctly in Mixxx. Test rollback without overwriting subsequent user changes.

Do not introduce guessed Mixxx columns or automatically replace beat grids. Audio tags remain untouched in this project phase.

## Development and testing approach

Use test-driven development for production behavior changes. Start each use case with domain or application tests using fake ports, then add adapter and infrastructure tests only where external behavior must be verified. Keep fast unit tests independent from Essentia, FFmpeg, SQLite files, Mixxx databases and network downloads. Mark real model inference and external-tool checks as integration or acceptance tests with explicit fixtures and resource requirements.

When implementing a feature, first identify the business rule or use case, choose the layer where it belongs, write the failing test at that layer, then add the smallest production change. Refactor only with tests green.

## Implementation milestones

| Phase                       | Deliverable                                             | Acceptance gate                                                                                      |
| --------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 1. Environment check        | Dependency specification and doctor command             | Each audio format decodes; every selected model loads and runs on the target machine                 |
| 2. Vertical slice           | Single-track CLI producing all six attributes           | Outputs match model shapes/labels and include provenance and coverage                                |
| 3. Catalogue and batch jobs | Scan, persistent queue, caching, resume and retries     | Interrupted batches resume; unchanged tracks skip work; corrupt files do not abort the library       |
| 4. Review and export        | List/show, uncertainty filters, overrides, JSON and CSV | Exports preserve identities and scores; manual edits survive reanalysis                              |
| 5. Pilot calibration        | 50–100 representative tracks reviewed                   | Document accuracy limitations, threshold choices, memory use and measured runtime                    |
| 6. Mixxx adapter            | Inspect, preview, backup and apply                      | Test copy opens correctly; failed transactions leave no partial changes; unrelated data is preserved |
| 7. Distribution             | Installable package and usage documentation             | Fresh installation succeeds and analysis works offline after model setup                             |

Select the pilot across the collection's styles, formats, durations and difficult cases, rather than simply taking the first 50 files. Estimate the full run from measured audio-duration throughput on the target machine.

## Phased implementation plan

Deliver small, test-driven vertical slices within each phase. Phases proceed in order, except that distribution preparation may begin earlier and does not depend on the optional Mixxx milestone. Do not implement deferred UI or service work as part of these phases.

### Phase 1 — Architecture foundation and environment validation

**Depends on:** confirmation of CPU architecture, RAM and the Python/Essentia installation route.

1. Create the package and boundary-oriented folders below, with a minimal CLI composition root and separate unit, integration and acceptance test suites.
2. Write failing application tests for `RunDoctor` using fake dependency, model and configuration probes. Implement the use case and wire concrete probes only at the composition root.
3. Add configuration loading and XDG path handling in infrastructure; pass validated settings into use cases rather than reading environment variables in inward layers.
4. Test and implement model manifest validation, download and verification through ports, including interrupted downloads, checksum failures and license records.
5. Run explicit integration checks for FLAC, MP3 and M4A decoding and every selected model on the target machine. Pin the working dependency combination.

**Acceptance gate:** `doctor` reports actionable setup failures; model setup is repeatable; all selected models load and run; domain/application tests need no external tools or network. Add an automated import-boundary check preventing inward dependencies on outer layers.

### Phase 2 — Single-track analysis vertical slice

**Depends on:** phase 1.

1. Write domain tests for predictions, coverage, ambiguity, aggregation, provisional energy interpretation and provenance before implementing those rules.
2. Define the minimum decoder, analyser, model and result repository ports needed by `AnalyzeTrack`. Test orchestration with fakes, including failed decoding and failed inference.
3. Implement FFmpeg and Essentia adapters, translating tool-specific arrays, metadata and exceptions into explicit boundary types. Keep preprocessing details outside domain policy.
4. Add analysis SQLite migrations and repository adapters, including rejection of unrelated database schemas. Persist stage results and provenance as stages complete.
5. Wire single-track analysis to CLI controllers and presenters. Preserve raw scores, timestamps and uncertainty rather than presenting scores as calibrated probabilities.

**Acceptance gate:** one track produces all six attributes with provenance and coverage; real-model fixtures verify tensor shapes and label order; failures are recorded and reported; audio tags and Mixxx remain untouched.

### Phase 3 — Catalogue, durable batches and recovery

**Depends on:** phase 2.

1. Test identity and reuse rules for duplicates, moved files, modified content and separate locations. Implement `ScanLibrary` over filesystem and metadata ports.
2. Test batch state transitions, bounded retries and interrupted-stage recovery with fake repositories and workers before implementing `AnalyzeBatch`.
3. Implement durable jobs, one database writer, an exclusive batch lock and bounded worker execution. Start with one worker and load models once per worker.
4. Add embedding caching and invalidation keyed by content identity, model hash, preprocessing and algorithm version. Test that threshold-only changes rerun aggregation without inference.
5. Wire status, retry, force and cancellation behavior into the CLI. Bound memory, temporary storage and input duration without silently truncating audio.

**Acceptance gate:** interrupted batches resume safely; completed unchanged work is skipped; corrupt tracks do not abort other jobs; concurrent batches are rejected; Ctrl+C checkpoints progress; failed batches return a non-zero exit code.

### Phase 4 — Review, manual overrides and exports

**Depends on:** phase 3.

1. Write domain tests for review flags and manual override precedence, including preservation across reanalysis.
2. Implement review queries and override updates through application use cases. Specify an explicit CLI operation for setting and clearing overrides before building its controller.
3. Implement list/show/status presenters and JSON/CSV export mappers over application DTOs, with output writing behind a port.
4. Add CLI acceptance tests for human-readable output, machine-readable JSON, stdout/stderr separation and uncertainty filtering.

**Acceptance gate:** users can inspect, set and clear overrides; overrides survive reanalysis; exports retain identities and scores; JSON parses reliably; CSV safely handles formula-like text, quotes and Unicode.

### Phase 5 — Representative pilot and calibration

**Depends on:** phase 4 and access to a representative local collection.

1. Select 50–100 tracks spanning styles, formats, durations and difficult cases; record listening-based judgments separately from model outputs.
2. Compare sampled and full-track coverage, including brief instrument appearances, changing tempo/key and uncertain material.
3. Measure audio-duration throughput, peak memory and cache/storage use on the target machine before changing worker counts.
4. Tune provisional thresholds using reviewed examples. If aggregation policy changes, add failing regression tests first and version the resulting policy.
5. Document limitations, chosen settings and estimated full-library runtime. Benchmark alternative models only for demonstrated weaknesses.

**Acceptance gate:** pilot findings and resource measurements are recorded; default coverage and thresholds have an explicit rationale; remaining accuracy limitations are disclosed rather than hidden behind numerical scores. No unvalidated accuracy target is implied.

### Phase 6 — Guarded Mixxx integration (optional milestone)

**Depends on:** phase 5, the actual Mixxx version and a disposable database copy. Analysis and export remain usable without this phase.

1. Inspect the real schema read-only and establish supported destinations for each attribute before implementing writes.
2. Write application/domain tests for verified track mapping, fill-missing versus replacement policy, expected old values and stale change-set rejection.
3. Implement inspection and preview through a Mixxx port and version-specific infrastructure adapters. Present the concrete change set for user review.
4. Test and implement database identity/schema checks, the Mixxx-closed precondition, WAL-aware backup and transactional application on disposable copies.
5. Test rollback conflicts and preservation of cue points, beat grids, playlists and unrelated metadata. Record before/after values and application outcomes for audit and recovery.

**Acceptance gate:** stale previews and unsupported schemas are rejected; failed batches leave no partial Mixxx updates; backups restore correctly; rollback does not overwrite later user changes; an updated test copy opens correctly in Mixxx. Never guess columns or automatically replace beat grids.

### Phase 7 — Packaging and release readiness

**Depends on:** phases 1–5; phase 6 only when shipping Mixxx integration.

1. Finalise the installable package, entry point and tested dependency specification without coupling domain/application code to packaging or CLI frameworks.
2. Document installation, model licensing, offline operation, resource limits, review workflows, cache cleanup and failure recovery.
3. Run unit and boundary checks, adapter/infrastructure integration tests and end-to-end CLI acceptance tests against the release revision.
4. Rehearse a fresh installation, model setup, scan, analysis, interruption/resume and export. Include Mixxx checks only when that milestone is included.

**Acceptance gate:** a fresh installation succeeds on the target environment; analysis works offline after setup; the documented workflow is reproducible; all shipped behavior has passing tests and dependencies still point inward.

## Validation priorities

- Verify model preprocessing, tensor names, label order and output dimensions against official examples.
- Exercise paths with spaces and Unicode, duplicate files, moved files, missing files and corrupt audio.
- Test silent, short and long tracks, half/double-time ambiguity and key/tempo variation.
- Test interrupted jobs, retries, changed models and cache invalidation.
- Verify JSON is machine-readable and CSV exports safely handle spreadsheet formula-like text.
- Test database identity checks and Mixxx writes only against disposable copies.
- Distinguish mocked orchestration tests from real model inference and listening-based validation.

## Proposed project layout

Prefer folders that make dependency direction and responsibilities explicit:

| Path                                            | Responsibility                                                                                                                                            |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pyproject.toml`                                | Package metadata, dependencies and CLI entry point                                                                                                        |
| `music_analyzer/domain/`                        | Entities and value objects for tracks, recordings, predictions, stages, provenance, summaries, overrides, review state and guarded change sets            |
| `music_analyzer/domain/services/`               | Pure domain services for invalidation, score interpretation, aggregation rules and override precedence                                                    |
| `music_analyzer/application/use_cases/`         | Orchestration use cases such as doctor, model setup, scan, analyze, status, review queries, export and Mixxx preview/apply                                |
| `music_analyzer/application/ports/`             | Interfaces for filesystem inventory, audio decoding, analysers, model registry/storage, persistence, transactions, Mixxx access, clock and output writing |
| `music_analyzer/application/dto/`               | Input/output DTOs for use-case boundaries; no framework request or database row objects                                                                   |
| `music_analyzer/interface_adapters/cli/`        | Command controllers, argument mapping and terminal presenters                                                                                             |
| `music_analyzer/interface_adapters/presenters/` | Human-readable, JSON and CSV presentation models                                                                                                          |
| `music_analyzer/interface_adapters/gateways/`   | Mappers between application models and SQLite rows, Essentia outputs, model manifests and Mixxx records                                                   |
| `music_analyzer/infrastructure/audio/`          | FFmpeg decoding and preprocessing implementations                                                                                                         |
| `music_analyzer/infrastructure/analysis/`       | Essentia rhythm/key analysers, embedding extraction and classifier inference implementations                                                              |
| `music_analyzer/infrastructure/persistence/`    | Analysis SQLite schema, migrations, repositories, locks and recovery persistence                                                                          |
| `music_analyzer/infrastructure/models/`         | HTTPS downloads, checksum validation, model asset storage and license/attribution records                                                                 |
| `music_analyzer/infrastructure/filesystem/`     | XDG paths, library walking, metadata probing and output file writing                                                                                      |
| `music_analyzer/infrastructure/mixxx/`          | Read-only inspection, schema mapping, backups and transactional Mixxx database updates                                                                    |
| `music_analyzer/frameworks/cli/`                | CLI composition root that wires concrete adapters to use cases                                                                                            |
| `tests/unit/domain/`                            | Fast domain tests for value objects, invalidation, aggregation and override rules                                                                         |
| `tests/unit/application/`                       | Use-case tests with fake ports for scan, analysis, retries, export and Mixxx change-set policy                                                            |
| `tests/integration/interface_adapters/`         | Mapper and presenter tests, including JSON/CSV escaping and CLI command mapping                                                                           |
| `tests/integration/infrastructure/`             | SQLite migrations/recovery, FFmpeg/Essentia smoke tests, model manifest verification and Mixxx disposable-copy tests                                      |
| `tests/acceptance/`                             | End-to-end CLI workflows over small fixtures                                                                                                              |
| `README.md`                                     | Installation, workflow, architecture boundaries, limitations and recovery                                                                                 |

Avoid shortcut modules such as top-level `store.py`, `audio.py`, `models.py` or `mixxx.py` that make infrastructure details easy to import from inward layers. If small files are useful, place them within the appropriate boundary folder.

## Deferred work

Quickshell/QML UI, a background socket service, source separation, custom model training and automatic folder watching are deferred. Keep analysis callable independently from the CLI so a future Omarchy plugin can reuse it.

## Details needed before implementation

Confirm CPU architecture, available RAM and the Python/Essentia installation route. Music folder paths can be supplied when scanning. Mixxx version and a database copy are needed only for the integration milestone. Neither QML configuration nor Omarchy plugin APIs are required for this CLI phase.

## References

- [Essentia pretrained models, examples and licensing](https://essentia.upf.edu/models.html)
- [Essentia RhythmExtractor2013](https://essentia.upf.edu/reference/std_RhythmExtractor2013.html)
- [Essentia KeyExtractor](https://essentia.upf.edu/reference/std_KeyExtractor.html)
- [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html)

This CLI plan supersedes the QML-first delivery sequence in the earlier implementation plan.
