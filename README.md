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
`remaining_validation`.

- **0:** all configured foundation availability checks passed.
- **1:** a setup check failed, or doctor could not produce a report.
- **2:** invalid command or options (including no command).

Exit 0 **does not mean analysis is ready**. `analysis_ready` is always false in
this slice. Platform identification is informational, not a supported-hardware
certification. Essentia discovery cannot prove it imports successfully or has
TensorFlow operators; FFmpeg version detection cannot prove any format decodes.

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

Phase 1 is **not complete**. Configuration/XDG path loading, model manifests,
downloads, hashes and attribution/license records remain unimplemented. CPU/RAM
suitability, Python/Essentia TensorFlow compatibility, FLAC/MP3/M4A decoding and
all selected models must be validated on the target machine before pinning a
working inference environment. Analysis, persistence, library scanning, exports
and Mixxx integration are later phases. Only `doctor` is currently shipped;
planned commands and global configuration options are intentionally absent.
