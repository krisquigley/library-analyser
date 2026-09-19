# Release preparation and user hand-off (not release acceptance)

Phase 7 packaging work can proceed while Phases 5 and 6 wait for user inputs.
It does **not** close their gates or the Phase 7 prerequisite/acceptance gate.
No inference stack is pinned. CI tests the dependency-free Linux CLI on Python
3.11–3.14, not Essentia compatibility, model accuracy or other operating systems.
The CI matrix is a verification target; consult the run for the exact revision
before claiming a tested combination. Build-only setuptools 84.0.0 is not an
inference dependency. Runner images/Python patch releases can change; CI is
repeatable in scope and fixtures, not a byte-reproducible build certification.

## Installation rehearsal and evidence

Use an explicit checkout revision and a fresh virtual environment. Do not use
`sudo pip`, upgrade an existing inference environment, or install model packages
based on guessed version combinations. From the checkout, after provisioning
Python with `venv`/pip and build tooling through your approved route:

```sh
python -m venv /tmp/music-analyzer-build
/tmp/music-analyzer-build/bin/python -m pip install setuptools==84.0.0
RUN_PACKAGING_TESTS=1 PACKAGING_ARTIFACT_DIR=/tmp/music-analyzer-artifacts \
  /tmp/music-analyzer-build/bin/python -m unittest tests.packaging.test_distribution -v
python -m unittest discover -s tests/unit -v
python -m unittest tests.architecture.test_import_boundaries -v
python -m unittest discover -v
# Optional; requires an already installed FFmpeg with FLAC/MP3/AAC support:
ffmpeg -version
RUN_FFMPEG_TESTS=1 python -m unittest tests.integration.infrastructure.test_audio_decode -v
```

The artifact test builds an sdist from a clean source copy, builds its wheel,
compares bundled official metadata/license bytes, installs offline with
`--no-index --no-deps` into a fresh environment, and runs console/module entry
points outside the checkout with isolated HOME/XDG paths. It scans **fake bytes**,
reviews annotations, exports JSON/CSV and checks non-overwrite behavior. It does
not analyze audio. Default discovery skips these build tests and real FFmpeg
integration; dependency-free unit tests never require either. Other acceptance
tests may run read-only `ffmpeg -version` discovery if available.

Save the revision, Python/platform versions, test logs and artifact SHA-256s.
To rehearse manually, install the resulting wheel in another fresh environment,
change to a directory outside the checkout, run `music-analyzer --help`, then
`doctor --json` and `models verify --json` with a new explicit model directory.
Absent models should report failure, not validated readiness. Do not invoke
`models download` until the user approves downloads and resolves licensing needs.
The bundled publisher model license is **not** a license grant for this project's
source; project redistribution licensing and the upstream model-license conflict
remain release decisions.

## Inputs for the representative pilot (Phase 5: not performed)

The user should supply a local, explicitly approved **copy-only** selection of
50–100 tracks, not their entire library or original directories. Keep files and
private manifests local; sharing audio or full paths in an issue is unnecessary.
Supply CPU architecture/model, RAM, free temporary/data/cache disk, OS and Python
versions, approved runtime installation route, and download approval separately.

Before seeing predictions, record a frozen selection manifest: anonymous ID,
SHA-256, format, duration, selection reason and optional privately held relative
path. Select reproducibly: define strata (styles, formats, duration bands), sort
candidate hashes within each stratum and record chosen hashes plus any seed and
selection procedure. Explicitly include brief instrument appearances, tempo/key
changes, half/double-time ambiguity, silence, very short/long tracks and uncertain
material. Record exclusions and duplicates; exact encodings have distinct IDs.
Do not imply random representativeness from convenient files alone.

Keep listening ratings in a separate local CSV/table, keyed by anonymous ID/hash:
reviewer, date, cue intervals, BPM alternatives, key/ambiguity, genres, moods,
instruments with audible time ranges, subjective energy rubric and uncertainty.
Use `unknown/not audible` rather than forced labels. Freeze the rubric first;
record disagreements and confidence. These are human judgments, not ground truth
probabilities. Retain raw model outputs separately. Reserve a holdout subset
before tuning; record thresholds, policy revision, evidence and failure examples.
Do not manufacture a default threshold or success percentage in advance.

After real inference and licensing gates clear, scan only the selected copy into
a new dedicated database; analyze explicit IDs first, then a limited single-worker
batch. Save run IDs, model receipts, runtime versions, recipe and coverage. The
current CLI uses sampled semantic sections, not selectable full-track semantic
inference. Full-track comparisons require a separately approved, tested extension
or validated reference workflow; no undocumented option is implied.

For resource measurements, record total attempted/completed audio seconds,
failures, wall seconds, cold/warm cache conditions, baseline/peak cache and database
bytes, peak temporary disk, and peak process-tree memory. On systems with GNU
`time` already available, `/usr/bin/time -v -o run-resources.txt <command>` provides
wall time and an RSS indicator; it is not a simultaneous process-tree memory or
peak disk meter. Record the monitoring method and sampling interval for decoder
children/native allocations and disk peaks, or explicitly mark those unmeasured.
Separate setup/model-load costs from warm runs; distinguish OS cache from embedding
cache and use fresh disposable XDG cache roots for cold runs. Compute completed
audio-seconds/wall-second with failures disclosed. Library runtime extrapolation
must state track-duration mix, hardware, cache assumptions and uncertainty.
Do not increase worker counts before target-machine measurements.

## Safe setup, backup and recovery rehearsal

- Use an existing writable parent directory and a **new dedicated** analysis DB.
  Never configure a Mixxx DB as `--database`. Keep originals outside the selected
  copy and do not grant this experiment write access to them where practical.
- Before upgrades or recovery, stop all analyzer processes. Save revision, config,
  model receipts/license/metadata, local pilot manifest and exports privately.
  Exports are review evidence, **not** a restorable database backup.
- Make a consistent SQLite backup with Python's stdlib `sqlite3.Connection.backup`
  from a read-only URI connection into a new destination, after stopping writers.
  Do not copy just the main file while WAL may contain committed data, discard
  sidecars, or use a live raw file copy as a backup. Check `PRAGMA integrity_check`
  returns `ok` on the backup and rehearse opening a **second copy** with the same
  CLI revision (`list`, `show`, `status`) before relying on it. These checks can
  initialize/migrate a database, so never test against your only backup.
- Retain the original backup immutable. Restore to a new dedicated path and
  explicitly select it; verify catalogue counts, annotations and stored runs.
  On unsupported schema/corruption, preserve files and errors rather than deleting
  tables or forcing migrations. An older CLI may not read a newer schema.
- Graceful Ctrl+C and batch restart retain checkpoints; restart starts a new full
  run for interrupted work, not partial-stage inference resume. `status` alone
  does not recover jobs. Do not delete a live `.batch.lock` or use hard-link DB
  aliases. Explicit single-file crashes may leave a running record.
- After stopping work, the embedding cache and abandoned audio/snapshot/temp
  download directories can be removed as described in README. Do not remove
  active temporary files. Cache loss costs recomputation, not stored annotations.
  Preserve invalid model bundles for investigation; verification does not repair
  them. Re-download only with renewed approval where required.

Rehearse these steps with disposable data and record actual results before
claiming recovery or offline analysis acceptance. No real pilot backup/restore
or real inference rehearsal is claimed by packaging tests.

## Mixxx input hand-off (Phase 6: blocked, not implemented)

Supply the exact Mixxx version/build, OS and how its database/profile is located.
With Mixxx closed, make a consistent disposable profile/database copy using the
version's documented backup process (including any required companion/WAL files).
Keep an untouched recovery copy. Confirm the supplied copy opens in that exact
Mixxx version in an isolated test profile without pointing at originals. Ask for
version-specific instructions if profile isolation or backup behavior is unclear.
Do not upload the DB publicly: it can contain full paths, playlists and history.
Provide only an explicitly approved local disposable-copy path initially.

The next implementation must inspect that actual schema read-only, verify track
mapping and supported attribute destinations, and test previews, old-value/stale
checks, transactions, backup restoration and cue/grid/playlist preservation.
No schema, columns, writes, preview/apply command or safe rollback is guessed here.
No current CLI command integrates with Mixxx.

## Remaining release gates

- [ ] User-approved runtime, model downloads and publisher licensing clarification.
- [ ] Real model execution, shapes/labels/preprocessing and offline inference.
- [ ] Target hardware resource limits and interruption/recovery rehearsal.
- [ ] Representative listening pilot, coverage comparison and calibrated rationale.
- [ ] Phase 3 broader recovery/queue-scaling work and outstanding earlier gates.
- [ ] Actual-version disposable Mixxx acceptance, only if shipping that milestone.
- [ ] Source redistribution licensing decision and final release metadata/version.
- [ ] CI success on the release revision and independent review (not performed here).
- [ ] Full fresh-install/setup/analysis/resume/export acceptance on target hardware.

Packaging preparation does not constitute Phase 7 release acceptance or a release.
