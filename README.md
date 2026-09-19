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

Options may appear before or after `doctor`. Precedence is **CLI > TOML >
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
human and JSON reports. It does **not** create directories, open SQLite, check
schemas or writability, download models, or establish model readiness. Selecting
a model directory is not evidence that models exist or can run. Future database
operations must still enforce schema/identity safety before writing anything.

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

Phase 1 is **not complete**. Model manifests, downloads, hashes and
attribution/license records remain unimplemented. CPU/RAM
suitability, Python/Essentia TensorFlow compatibility, FLAC/MP3/M4A decoding and
all selected models must be validated on the target machine before pinning a
working inference environment. Analysis, persistence, library scanning, exports
and Mixxx integration are later phases. Only `doctor` is currently shipped;
other planned commands are intentionally absent.
