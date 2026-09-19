# Local Music Analyser — CLI Implementation Plan

## Goal

Build a local command-line tool to analyse approximately 3,000 FLAC, MP3 and M4A files for BPM, key, mood, energy, genres and instruments. Save reviewable results and subsequently apply selected updates to Mixxx.

Target environment: the user's Omarchy Quattro Linux installation. This phase delivers a CLI; a future Quickshell interface can reuse its backend. Audio remains local. Internet access is needed only for installing dependencies and downloading models.

This document is a plan, not an implemented or validated tool. Command names below describe the intended interface.

## Technical approach

Use Python for orchestration, FFmpeg for audio decoding, Essentia for music analysis and pretrained inference, and SQLite for persistent results. Keep analysis and Mixxx integration in separate modules.

| Attribute | Initial library/model | Output |
| --- | --- | --- |
| BPM | Essentia RhythmExtractor2013, multifeature | BPM, native confidence, beat positions and section consistency |
| Key | Essentia KeyExtractor | Key, major/minor scale, strength and section estimates |
| Genres | Discogs-EffNet embeddings + genre_discogs400-discogs-effnet | Ranked genre/style labels and raw model scores |
| Mood | mtg_jamendo_moodtheme-discogs-effnet | Multiple mood/theme tags and scores |
| Instruments | mtg_jamendo_instrument-discogs-effnet | Instrument categories, scores and section presence |
| Energy | MSD-MusiCNN embeddings + emomusic-msd-musicnn | Raw arousal/valence and provisional 0–100 energy score |

Reuse compatible Discogs-EffNet embeddings across the genre, mood and instrument classifiers. The energy model uses a separate MusiCNN representation. Follow each model's metadata for preprocessing, sample rate, tensor names and class ordering.

Use pretrained weights initially. Benchmark alternatives only when the pilot identifies a concrete weakness. MTG models carry CC BY-NC-SA terms; retain their license and attribution information with the downloaded assets.

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

| Record | Purpose |
| --- | --- |
| Tracks and locations | File identity, paths and source metadata |
| Jobs and stage results | Pending/running/completed/failed state and restart recovery |
| Segments and predictions | Window timestamps, model scores and coverage |
| Summaries and overrides | Derived tags and preserved user corrections |
| Model versions and runs | Model hashes, preprocessing settings and dependency versions |
| Export batches and changes | Proposed/applied Mixxx values and audit history |

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

## Implementation milestones

| Phase | Deliverable | Acceptance gate |
| --- | --- | --- |
| 1. Environment check | Dependency specification and doctor command | Each audio format decodes; every selected model loads and runs on the target machine |
| 2. Vertical slice | Single-track CLI producing all six attributes | Outputs match model shapes/labels and include provenance and coverage |
| 3. Catalogue and batch jobs | Scan, persistent queue, caching, resume and retries | Interrupted batches resume; unchanged tracks skip work; corrupt files do not abort the library |
| 4. Review and export | List/show, uncertainty filters, overrides, JSON and CSV | Exports preserve identities and scores; manual edits survive reanalysis |
| 5. Pilot calibration | 50–100 representative tracks reviewed | Document accuracy limitations, threshold choices, memory use and measured runtime |
| 6. Mixxx adapter | Inspect, preview, backup and apply | Test copy opens correctly; failed transactions leave no partial changes; unrelated data is preserved |
| 7. Distribution | Installable package and usage documentation | Fresh installation succeeds and analysis works offline after model setup |

Select the pilot across the collection's styles, formats, durations and difficult cases, rather than simply taking the first 50 files. Estimate the full run from measured audio-duration throughput on the target machine.

## Validation priorities

- Verify model preprocessing, tensor names, label order and output dimensions against official examples.
- Exercise paths with spaces and Unicode, duplicate files, moved files, missing files and corrupt audio.
- Test silent, short and long tracks, half/double-time ambiguity and key/tempo variation.
- Test interrupted jobs, retries, changed models and cache invalidation.
- Verify JSON is machine-readable and CSV exports safely handle spreadsheet formula-like text.
- Test database identity checks and Mixxx writes only against disposable copies.
- Distinguish mocked orchestration tests from real model inference and listening-based validation.

## Proposed project layout

| Path | Responsibility |
| --- | --- |
| pyproject.toml | Package metadata, dependencies and CLI entry point |
| music_analyzer/cli.py | Commands and output formatting |
| music_analyzer/catalog.py | Scanning and file identity |
| music_analyzer/audio.py | Decoding and preprocessing |
| music_analyzer/analyzers/ | Rhythm, key, semantic and energy modules |
| music_analyzer/models.py | Downloads, metadata and integrity checks |
| music_analyzer/jobs.py | Durable batch execution and recovery |
| music_analyzer/store.py | Analysis schema and migrations |
| music_analyzer/export.py | JSON/CSV and review output |
| music_analyzer/mixxx/ | Version-specific inspection and transactional updates |
| tests/ | Focused fixtures and integration tests |
| README.md | Installation, workflow, limitations and recovery |

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
