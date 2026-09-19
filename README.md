# Local Music Analyser — foundation slice

This repository implements **only a bounded part of Phase 1** of
[the CLI plan](plans/music-analyzer-cli-plan.md). It does not analyse audio yet.
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
required by the XDG specification. No cache is used in this slice.

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
