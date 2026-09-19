# Local Music Analyser — incremental foundation

This repository implements **partial Phase 1 and an unvalidated Phase 2 single-track implementation**
of [the CLI plan](plans/music-analyzer-cli-plan.md). The CLI can invoke real Essentia APIs when dependencies and approved models are
installed; no real model inference has been validated.
`doctor` reports Python/platform information, checks `ffmpeg -version` (five-second
timeout), and discovers the top-level Essentia module **without importing it**.
No runtime third-party Python dependencies are needed for this slice.

## Install and run

Python **3.11+** is required for this CLI, not a promise of Essentia compatibility.
The foundation tests and installation were exercised with Python 3.14.7 on Linux;
no working inference dependency combination has been selected or pinned.

```sh
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/music-analyzer doctor
.venv/bin/music-analyzer doctor --json
# Equivalent module entry point:
.venv/bin/python -m music_analyzer doctor --json
```

Installation may obtain setuptools from your configured package index. Doctor
itself uses no network, downloads nothing, does not install dependencies, and
writes no music, models, databases, configuration, or Mixxx data. Missing tools
produce suggested next steps; the user must choose and perform any installation.

### Output and exit status

Human reports and JSON reports go to **stdout**, even when checks fail. Usage
errors and unexpected execution errors go to **stderr**; JSON output is never
mixed with progress text. `doctor --json` includes `checks` (name, availability,
detail, remediation), `foundation_ready`, `analysis_ready`, and
`remaining_validation`, and resolved `settings`.

- **0:** all configured foundation availability checks passed.
- **1:** a setup check failed, or doctor could not produce a report.
- **2:** invalid command, options, or configuration (including no command).

Exit 0 **does not mean analysis is ready**. `analysis_ready` is always false in
this slice. Platform identification is informational, not a supported-hardware
certification. Essentia discovery cannot prove it imports successfully or has
TensorFlow operators; FFmpeg version detection cannot prove any format decodes.

## Configuration and overrides

Options may appear before or after `doctor`, or at any level of `models download` / `models verify`. Precedence is **CLI > TOML >
defaults** for each setting. An explicit `--config` replaces the default config
file; it does not merge with it. Repeated CLI options use the last value.

```sh
music-analyzer --config /path/to/config.toml doctor --json
music-analyzer doctor --database /path/to/analysis.sqlite --model-directory /path/to/models
```

The optional default file is `$XDG_CONFIG_HOME/music-analyzer/config.toml`, or
`~/.config/music-analyzer/config.toml` when `XDG_CONFIG_HOME` is unset, empty or
relative. Default data paths are:

- `$XDG_DATA_HOME/music-analyzer/analysis.sqlite`
- `$XDG_DATA_HOME/music-analyzer/models`

`XDG_DATA_HOME` falls back to `~/.local/share` when unset, empty or relative, as
required by the XDG specification. Embeddings use XDG cache (see the cache slice below).

The TOML format has two optional **top-level** keys (no section header):

```toml
database = "/home/alice/.local/share/music-analyzer/analysis.sqlite"
model_directory = "models"
```

Relative TOML paths are relative to the config file's directory. Relative CLI
paths (including `--config`) are relative to the invocation's working directory.
TOML strings are literal paths: `~` and environment variables are not expanded
(use absolute paths; your shell may expand unquoted CLI paths).

A missing default config is normal. A missing explicit config, unreadable or
malformed TOML, unknown keys, non-string/empty paths, or existing paths of the
wrong kind produce actionable errors on stderr with exit status 2. Config values
are checked even if overridden; final target paths and their existing parents
are checked for file/directory conflicts. Missing target directories are allowed.

Doctor displays the selected paths and whether a config file was loaded in both
human and JSON reports. It verifies the selected model bundles read-only. It does **not** create
directories, open SQLite, check schemas or writability, download models, or
establish inference readiness. Selecting
a model directory alone is not evidence that models exist or can run. Future database
operations must still enforce schema/identity safety before writing anything.

## Model setup (integrity, not inference)

```sh
music-analyzer models verify --json
music-analyzer models download --model-directory /path/to/models
music-analyzer --config /path/to/config.toml models verify
music-analyzer doctor --json
```

`download` fetches the six pinned graphs below, sequentially over HTTPS from
`essentia.upf.edu` only, with certificate validation, restricted redirects,
30-second socket timeout and manifest size limits. No weights were downloaded
or executed during this delivery; tests use tiny fake transfers. The official
HTTP HEAD sizes measured for this selection total **29,151,559 bytes (27.80 MiB)**.
Allow roughly 30 MiB for a fresh installation including metadata/licenses; when
retaining an old copy for recovery allow another complete copy. Real download
and target inference validation still require explicit approval.

| Model / role | Version | Graph bytes | Official metadata (ordered labels, tensors, preprocessing and attribution) |
| --- | --- | ---: | --- |
| Discogs-EffNet embeddings | bs64-1 | 18,366,619 | [metadata](https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.json) |
| MSD-MusiCNN embeddings | 1 | 3,197,999 | [metadata](https://essentia.upf.edu/models/feature-extractors/musicnn/msd-musicnn-1.json) |
| Discogs400 genre head | 1 | 2,057,977 | [metadata](https://essentia.upf.edu/models/classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1.json) |
| Jamendo mood/theme head | 1 | 2,739,668 | [metadata](https://essentia.upf.edu/models/classification-heads/mtg_jamendo_moodtheme/mtg_jamendo_moodtheme-discogs-effnet-1.json) |
| Jamendo instrument head | 1 | 2,706,836 | [metadata](https://essentia.upf.edu/models/classification-heads/mtg_jamendo_instrument/mtg_jamendo_instrument-discogs-effnet-1.json) |
| Emomusic valence/arousal head | 2 | 82,460 | [metadata](https://essentia.upf.edu/models/classification-heads/emomusic/emomusic-msd-musicnn-2.json) |

The bundled manifest retains official JSON metadata without reordering classes
(genre 400, mood 56, instrument 40; Emomusic order is **valence, arousal**).
All selected metadata specifies 16 kHz input audio for the embedding pipeline;
heads consume embeddings, not raw audio. The [official examples](https://essentia.upf.edu/models.html)
select Discogs-EffNet `PartitionedCall:1` and MusiCNN `model/dense/BiasAdd`
embeddings. Some head metadata retains older Discogs embedding URLs; those
records remain verbatim, while downloads use the current official feature
extractor URL. No preprocessing, tensor shape, dependency build or inference
compatibility has yet been tested on target hardware.

**License discrepancy requiring publisher clarification:** the official models
page states **CC BY-NC-SA 4.0**, but the official
[LICENSE](https://essentia.upf.edu/models/LICENSE) has a
**Attribution-NonCommercial-NoDerivatives 4.0** heading and legal text, while its
summary links to BY-NC-SA legalcode. Do not treat this tool as resolving that
conflict or granting commercial/derivative rights. The complete publisher
LICENSE (including third-party notices), original authors/citations and this
warning are retained with every bundle. Contact MTG for clarification or
proprietary licensing as appropriate.

Each `<model-directory>/<model-id>/` contains `model.pb`, `metadata.json`,
`LICENSE` and `receipt.json`. A fresh bundle is staged in a unique temporary
sibling directory, checked, flushed and renamed only after completion. Failures
and Ctrl+C remove the active temporary directory; hard process/machine failure
may leave a `.download-*` directory, which can be removed manually when no
installer is running. No automatic partial-download resume or repair is done.
Verified existing bundles are reused without network access. Invalid existing
bundles fail closed: inspect/move the named bundle aside, then retry download.
Model paths containing symlinks are rejected. Avoid concurrent installers and
untrusted mutation of the configured model directory; this is not a hostile
multi-user filesystem sandbox or a power-loss durability guarantee.

No publisher SHA-256 was supplied by the primary metadata examined. Receipts
therefore label these graphs **local-sha256**: verification detects changes
against the locally recorded bytes and checks the pinned size, original metadata
and license. It does not authenticate publisher bytes, detect simultaneous
malicious replacement of both graph and receipt, validate a TensorFlow graph,
or prove successful inference. The storage adapter distinguishes publisher
checksums if a future curated manifest supplies one. There is deliberately no
user-supplied manifest/URL option.

Model reports go to stdout in human or JSON form (`models`, `ready`,
`inference_validated`); each result includes `model_id`, `available`, `integrity`
and `detail`. Exit **0** means all bundles pass integrity, **1** means setup or
transfer failure, **2** means invalid usage/configuration, **130** means Ctrl+C.
Doctor now includes a model integrity check in `foundation_ready` but always
reports `analysis_ready: false`. Verification and doctor work offline and write
nothing; only explicit `models download` writes model bundles. Neither command
opens music or Mixxx data or the configured analysis database.

## Tests and architecture

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m unittest discover -s tests/unit -v
.venv/bin/python -m unittest tests.architecture.test_import_boundaries -v
```

Tests use the standard-library `unittest` runner. Application tests use fake
probes, with no external tools or heavy inference imports. Infrastructure tests
mock process execution and module discovery. CLI acceptance tests launch the
actual module and perform read-only local discovery (FFmpeg may run if present);
they accept an actionable missing-dependency report, not real inference success.

- `music_analyzer/application/{dto,ports,use_cases}`: immutable readiness results,
  the small probe protocol, and `RunDoctor` orchestration/readiness policy.
- `music_analyzer/application/ports/models.py`: model storage and transfer boundaries.
- `music_analyzer/infrastructure/models`: curated manifest, HTTPS and atomic filesystem bundles.
- `music_analyzer/infrastructure/config.py`: read-only TOML loading and XDG/path validation.
- `music_analyzer/infrastructure/environment`: Python/platform, FFmpeg, and
  Essentia discovery adapters.
- `music_analyzer/interface_adapters/presenters`: human and JSON translation.
- `music_analyzer/frameworks/cli`: argparse entry point and concrete composition.

No domain folder or future ports are created yet: dependency availability is an
application concern, and there are no music-domain rules in this slice. Automated
AST checks enforce layer dependencies, restrict inner-layer imports to a small
stdlib allowlist, and test rejection of representative forbidden imports. These
checks are architectural regression tests, not a security sandbox.

## Still deferred

Phase 1 is **not complete**. CPU/RAM
suitability, Python/Essentia TensorFlow compatibility, FLAC/MP3/M4A decoding and
all selected models must be validated on the target machine before pinning a
working inference environment. Analysis, persistence, library scanning, exports
and Mixxx integration are later phases. Only `doctor`, `models download` and `models verify` are shipped;
other planned commands are intentionally absent.

## Phase 2 backend increment (not the six-attribute acceptance gate)

The callable `AnalyzeTrack` use case now orchestrates six ordered stages through
explicit decoder, analysis-engine and repository ports. Tests use fake engines;
these fixtures are not music predictions. Each successful stage is committed
before the next. Expected failures retain earlier stages and stop the run;
interruptions clean up audio and record an interrupted run. Unexpected programming
errors propagate and can leave a running row; crash recovery is deferred.

A real FFmpeg adapter decodes a local file once to disposable 44.1 kHz mono
float32 PCM. It does not edit the input. The decoder does not buffer the full track; rhythm/key each load the capped
track into memory. Essentia/TensorFlow internal allocations are not OS-limited.
Default application duration cap is 900 seconds (~152 MiB temporary PCM), with
an explicit hard maximum of 3600 seconds (~606 MiB). One extra second detects
oversized inputs, which are rejected rather than silently truncated. Decode has
a 120-second wall timeout, and normal failure/interrupt paths remove temporary
files. Hard process kills may leave OS-temp directories named
`music-analyzer-audio-*`; remove only abandoned directories. Actual disposable
FLAC, MP3 and M4A decode tests pass with the installed FFmpeg. These silent
one-second fixtures do not validate rhythm, harmony or semantic inference.

`SQLiteAnalysisRepository` initializes a dedicated empty database transactionally
with an application ID and schema version 3 (transactional v0 → v1 → v2 → v3). It rejects unrelated schemas,
unknown versions, symlink paths and Mixxx-named databases; it stores separate run
IDs, source locations, stage results, uncertainty and provenance. It never opens
the music file. Parent directories must already exist. Identity is not a security
boundary against hostile concurrent local replacement. The v1 → v2 migration adds
tracks, locations and root membership without rewriting runs or stage/provenance
payloads. The v2 → v3 migration adds batch jobs without rewriting existing records. No migration from other applications. Never point it at a Mixxx database.

A provisional pure score summary retains duration-weighted mean, minimum,
maximum and explicit disjoint-window coverage. It does not select tags, infer
sustained instrument presence, calibrate probabilities or invent an energy
scale. The semantic adapter uses this policy for section summaries.

### Single-file CLI (experimental, inference acceptance still open)

```sh
music-analyzer analyze --file /path/to/track.flac --database /existing/directory/analysis.sqlite
music-analyzer analyze --file /path/to/track.flac --max-duration 900 --json
```

`--file` is explicitly a local path. Alternatively, `--track TRACK_ID` resolves
a catalogue location and rehashes it before dispatch; the selectors are mutually
exclusive. Unknown/missing/changed tracks require a rescan. Each explicit
`--file` or `--track` invocation starts a new run; batch-only options are rejected. Database parent directories must exist. No audio tags or Mixxx writes.
Config options work before or after `analyze`. Exit 0 means all stages completed,
1 means setup/analysis failure, 2 argument/configuration error, 130 interrupt.
JSON contains all stage values, windows, summaries, uncertainty and provenance;
setup failures have a null run ID. Human output truncates semantic labels to top
10 for display only; these are not threshold-selected tags.

RhythmExtractor2013 uses multifeature at 44.1 kHz; KeyExtractor uses 44.1 kHz.
They currently provide whole-track estimates, not section ambiguity checks.
Semantic inference uses all audio up to 90 seconds, otherwise three disjoint
30-second beginning/middle/end sections. Coverage is **section exposure**, not
independent receptive-field coverage. Native overlapping patch predictions are
averaged per section, then weighted by section duration; min/max are section
means, not frame extrema. Final patches are repeated by the official predictor;
Effnet fixed batches use `lastBatchMode=same`, excluding padding-only predictions.
Discogs embeddings are reused across genre/mood/instrument heads. Emomusic uses
its separate MusiCNN embeddings and metadata order `(valence, arousal)`; raw
arousal is only a provisional energy proxy, not a calibrated DJ energy score.
No guessed tensor names, class orders, custom spectrograms or fake inference
fallbacks. Verified local model hashes and Essentia version accompany results.
Catalogue hashes are exact-file identities only. Runs record source paths and
verified snapshot/PCM provenance; persistent embedding reuse is described below.

**Open acceptance work:** real graph execution and shape/label/preprocessing
validation, compatible pinned inference stack, CPU/RAM measurements, section
rhythm/key ambiguity checks, independent review and accuracy evaluation.
Python 3.14 on this host has no Essentia; optional libraries load lazily and
produce actionable setup errors. No weights downloaded or real inference run.
Download approval and publisher-license clarification remain outstanding.
Model verification is integrity checking, not proof of inference readiness.
The Phase 1 inference gate and Phase 2 acceptance gate remain **open**; Phase 3
catalogue, durable batch and embedding cache delivery is partial; later Mixxx integration
remain unimplemented.

Official APIs consulted: retained model metadata, plus MTG/essentia upstream
`src/algorithms/machinelearning/tensorflowpredict{effnetdiscogs,musicnn,2d}.{h,cpp}`,
`src/algorithms/rhythm/rhythmextractor2013.cpp`, and
`src/algorithms/extractor/keyextractor.cpp` at
https://github.com/MTG/essentia . API reference host requests timed out during
this delivery; upstream source snapshots were retained externally instead.


### Phase 3 catalogue foundation (bounded slice, not Phase 3 completion)

```sh
music-analyzer scan /explicitly/selected/music --database /existing/directory/analysis.sqlite --json
music-analyzer scan /explicitly/selected/music --max-entries 10000 --max-file-bytes 536870912 --max-total-bytes 8589934592
music-analyzer analyze --track sha256:DIGEST_FROM_SCAN --database /existing/directory/analysis.sqlite --json
```

Only the supplied directory is inventoried. No default music directory, tag writes,
Mixxx access, metadata network requests or model downloads. Supported inventory
extensions: FLAC, MP3, M4A, WAV, OGG, OPUS, AIFF/AIF (case insensitive). This slice
records filesystem metadata (size, nanosecond mtime, extension) and streaming
SHA-256, **not audio tags, duration, codec validation or acoustic fingerprints**.
Malformed audio can enter the catalogue and later fail decoding. Other extensions
are ignored. Symlink files/directories are skipped; a symlink root/ancestor is
rejected. Special files are never read. Unicode locations remain distinct.

Track IDs are `sha256:<exact-byte digest>`: identical copies share an ID but retain
separate location rows. Moving identical bytes preserves the ID; changed bytes
create a different identity at that path. Different encodings are not merged.
Every scan rehashes; metadata-only fast skipping and result reuse are not claimed.
A successful complete rescan marks previously registered, now-absent locations
under that exact root unavailable, retaining historical tracks/locations.
Errors or exhausted limits produce a partial report (exit 1) and never mark missing
locations; successful files are still registered atomically. Scan issues are
returned, not stored as durable jobs. Root membership supports repeated and
overlapping roots; missing detection requires rescanning the same root.

Defaults bound entries (including directories/ignored entries) to 10,000, files to
512 MiB each and attempted hashing to 8 GiB total; configurable hard ceilings are
100,000 entries, 2 GiB/file and 64 GiB total. Memory uses 1 MiB hash chunks plus
bounded inventory records. Select smaller roots or raise explicit limits when
reported. No wall-clock deadline or protection from a hostile concurrently mutated
filesystem is promised. Stat checks detect ordinary mutation during hashing, but
files can still change during catalogue inspection. Analysis now verifies a
private snapshot before decoding. Both `--track` and `--file` analysis use a
512 MiB snapshot cap even if the scan inventory cap was raised.

The next bounded cache/snapshot slice is delivered below; Phase 3 acceptance remains partial. Review/export, calibration and Mixxx
remain later work. Real inference is still unvalidated; no models were downloaded.


### Durable single-worker batch slice (Phase 3 still incomplete)

```sh
music-analyzer analyze --database /existing/directory/analysis.sqlite --limit 10 --json
music-analyzer analyze --database /existing/directory/analysis.sqlite --retry-failed
music-analyzer analyze --database /existing/directory/analysis.sqlite --force --limit 1
music-analyzer status --database /existing/directory/analysis.sqlite --json
```

Without `--file`/`--track`, analyze selects available catalogue identities in stable
track-ID order. One worker loads models once, attempts tracks sequentially and
persists pending/running/completed/failed jobs. `--limit` caps attempts, not scans
or identity checks; no unsafe parallelism is provided. Failed tracks do not abort
other tracks. Defaults do not retry failures; `--retry-failed` permits one attempt
per eligible track this invocation, with three attempts total per recipe.
`--force` resets that budget and reruns selected tracks including completed ones.
A changed recipe starts a fresh budget. Attempts interrupted by Ctrl+C count.

A nonblocking POSIX advisory lock beside the database rejects a second batch
process. Keep the `.batch.lock` file; never delete it while a dispatcher runs.
Use one canonical database pathname (hard-link aliases are not supported).
Status is observational and does not recover or dispatch. It lists existing jobs,
not yet-unattempted catalogue entries; it exits 0 on successful inspection even
if jobs failed. Batch exit 1 means setup failure or any stored failed job, 130
means interrupted, and 0 does **not** mean the entire catalogue was attempted when
using a limit. JSON includes counts and job records, not full stage payloads.

Ctrl+C stops dispatch and checkpoints the current job pending. Restart recovers
abandoned running jobs, marks their bound runs interrupted, retains completed
stage payloads, and starts a **new full run**, not partial-stage reuse (valid embedding cache entries may still be reused).
Each real worker run is transactionally bound to its job before stage writes.
Old runs are retained even when force or a recipe change replaces a job pointer.

Completed jobs skip only after current exact bytes verify and the recipe matches:
verified local model hashes and manifest, Essentia/NumPy and FFmpeg versions,
preprocessing, duration cap, and hashes of algorithm/decoder/aggregation source.
Unavailable models/runtime fail setup even for potentially skippable jobs; no
weights are downloaded implicitly. The selected source is rehashed after success;
ordinary identity changes fail the job. The verified private snapshot described
below additionally binds decoding against source change-and-restore races.
No reuse of legacy explicit runs or invented cache hits. Persistent embedding
reuse is now available as described below.
Queue/status materialize catalogue job metadata in memory; audio/temp/duration
bounds remain as above, with a single worker. No real inference acceptance is
claimed by the fake-engine tests, and weights approval remains pending.


### Persistent embedding cache and verified decode snapshots (bounded Phase 3 slice)

Both explicit and batch analysis now inject a disposable embedding cache through
an application port. Compatible classifier heads share embeddings, not predictions.
The key includes the SHA-256 of the **actual private source snapshot and decoded
PCM**, verified embedding-model hash and metadata/tensors, Essentia/NumPy version,
mono 44100Hz float32/resampling policy, engine implementation hash, target rate,
duration and exact sampled sections. Head/threshold changes do not invalidate a
compatible embedding; head inference still runs in a new analysis. Corrupt, absent,
wrong-shape or nonfinite entries recompute. Unidentified fake/custom decoder output
never enters persistent caching. Model verification/runtime are still required on
hits, and decoding still runs to establish verified PCM identity; this is not a
whole-run or decoded-audio cache.

FFmpeg reads a private, read-only compressed snapshot, not the changing source
path. Copying is bounded to **512 MiB**, in 1 MiB chunks. Catalogue-resolved inputs
carry the expected content hash: snapshot mismatch fails with a rescan request.
Even a change-and-restore during decode cannot substitute different bytes after
snapshot verification. Explicit files bind results/cache to the bytes actually
copied; they do not assert catalogue identity. This is ordinary concurrent-source
mutation protection, not protection against a malicious same-user process or
model-file replacement. Existing post-run batch checks remain in place.
Temporary snapshots and decoded PCM are removed on normal exit, error and Ctrl+C.
The existing 3600s hard PCM cap (~606 MiB) and 120s decoder timeout remain; snapshot
plus PCM can require ~1.1 GiB temporary disk per worker. Abrupt kill/power loss can
leave temporary directories; do not remove directories of running analyses.

Cache location: `$XDG_CACHE_HOME/music-analyzer/embeddings-v1` when the XDG value
is absolute, otherwise `~/.cache/music-analyzer/embeddings-v1`. JSON entries contain
only finite rectangular embedding data and an integrity digest (not executable
pickle). Writes use same-directory temporary files, flush/fsync and atomic replace;
failed writes leave the old entry usable. Limits: **16 MiB serialized per entry**,
**256 MiB total after successful writes**, oldest-write eviction (not LRU). Oversized
entries and unwritable/full caches fall back to inference; cache durability is not
required for correctness. Independent explicit processes can temporarily exceed
the directory bound; no global cache lock or background cleanup is claimed.
After stopping analysis, deleting this directory is safe. Hidden `.write-*` remnants
from abrupt termination are disposable and not counted by eviction. No decoded
library copies are retained in the cache. Native model tensors/predictors remain
subject to real-runtime resource validation, not these serialized-file limits.

New stage JSON retains **raw native per-patch predictions** by section, in addition
to existing section score windows, provenance and summaries. No database migration
was needed; old stage bytes remain untouched and may lack raw predictions. The
inward `select_scores(labels, windows, duration, threshold)` capability creates a
provisional threshold view of retained scores without invoking any inference.
There is **no threshold/reaggregation CLI or persisted review selection yet**:
Phase 4 must add a read/mapping port for stored stages, expose this operation and
handle legacy payloads explicitly. Thresholds are not calibrated tag assertions.

Tests use fake model adapters and disposable audio, not downloaded weights.
**Real inference remains unvalidated**, Phase 1/2 gates remain open, and this does
not declare all Phase 3 complete. Remaining work includes compatible real-runtime
validation/resource measurements, broader recovery review, metadata queue scaling,
review/export/overrides, calibration and later Mixxx integration.
