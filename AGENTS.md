# AGENTS.md

This file guides Claude Code and other coding agents, and humans, working in this repository. Its rules are mandatory.

## Project

Local Music Analyser: a local, privacy-preserving toolkit for understanding a personal music library. It catalogues audio files the user explicitly selects, analyses them (tempo, key, and provisional genre, mood, instrument and energy scores from pretrained Essentia models), keeps the evidence in a dedicated SQLite database, and lets the user review, annotate, export and explore it, including a 3D mood-axis graph and playlist generation. The architecture below is non-negotiable.

### Decisions

- **Python 3.11+**, standard-library `unittest`, one distribution with **two packages**:
  - `music_analyzer` (`music-analyzer`) writes the analysis database: scan, analyze, review, override, export, graph build, integrity.
  - `music_explorer` (`music-explorer`) is a read-only localhost web explorer of that database. It **never writes** it; the one thing it may write is an audio file's tags, by an explicitly approved action (see below). The flow is always **analyzer writes → explorer reads**.
- **The analysis database is the only store.** The analyzer validates data when it writes it. The Explorer reads in read-only SQLite mode and checks only the rows each request reads. Full audits belong to the offline `music-analyzer integrity` diagnostic, never to Explorer reads.
- **Local and private.** Nothing is uploaded; only `models download` uses the network.
- **Audio is never edited; tags only with explicit approval.** Audio data is never written. Tags are written only from the Explorer GUI, after the listener has previewed and explicitly approved that particular action (#132). Approval never carries over to another action, and nothing writes tags automatically or in bulk. This is the only thing the Explorer writes; it still never writes the analysis database.
- **Never point anything at an existing Mixxx database**: don't open, read or write one. Exporting to a *new* Mixxx-compatible database file is allowed (#133). The export refuses an output path that already exists.
- **Evidence, not invented tags.** Model scores are uncalibrated and provisional. Keep raw scores, coverage, uncertainty and provenance, and let manual overrides win without discarding the automatic evidence.
- **No private data in the repository, issues or PRs.** Use synthetic or generated fixtures only. Never commit or post library paths, titles, databases, audio, screenshots, HAR files or response bodies.
- **Podman, never Docker.** Use `podman` for all container work. Never invoke the `docker` CLI or assume a Docker socket; an adapter named `docker` must be configured for Podman. If Podman is unavailable or misconfigured, report the blocker; never fall back to Docker.
- **Owner decisions in force:**
  - The Explorer track list shows 100 rows per page ("UI100"), and the graph starts loading automatically. Don't change either behaviour without the owner's approval.
  - No read-side cache, full-text search or new index (#18, #19) unless measurements at scale justify it and the owner agrees.
  - 5k/20k-track graph campaigns and optimisation (#44) are deferred until performance is a problem again.
  - The analyzer's and the standalone Explorer's search behaviours differ on purpose; preserve that difference.
  - Performance ceilings (#86): server selection path p95 ≤ 10 ms; 12-track settled detail-ready p95 ≤ 100 ms. A change counts as an improvement at ≥ 20% faster p50 with no p95 regression. **Never adjust a ceiling to make a change pass.**
  - Performance is measured only under the Podman supervisor (`tools/explorer_browser_gate.py` limits) with modest public synthetic fixtures. Results are descriptive values (p50/p95/max, failures, SHAs), never budgets asserted in tests.

## Architecture: Clean Architecture

Write this code as Robert C. Martin ("Uncle Bob") would. Follow *Clean Architecture*, *Clean Code* and the SOLID principles strictly. When in doubt, ask: "Would Uncle Bob accept this in a code review?" Prefer simple, explicit, boring code over clever abstractions.

**The directory structure is the architecture.** Every architectural boundary is a directory boundary, and every directory boundary is an architectural boundary. A reader should see the layers, and what the system does, from the file tree alone.

### The Dependency Rule

Source code dependencies point **inward only**.

```
frameworks  ──▶  infrastructure / interface_adapters  ──▶  application  ──▶  domain
(outermost)                                                                   (innermost)
```

- `domain/` imports nothing outside `domain/` (plus a small standard-library allowlist).
- `application/` imports only `domain/` and itself.
- `interface_adapters/` and `infrastructure/` import inward, never `frameworks/`.
- `frameworks/` is the composition root: the only place that knows every layer and wires concrete implementations.
- No name declared in an outer layer (SQLite row, HTTP request, CLI argument, framework object) may be mentioned in an inner layer.
- When control must flow outward (a use case saving a run, reading tracks), the inner layer declares a port in `application/ports/` and an outer layer implements it.
- `music_explorer`'s `domain/` and `application/` never import `music_analyzer`. The two packages stay independent; mirror an outward adapter with contract tests rather than share inner layers.

The rule is enforced by AST import checks in `tests/architecture/` (`test_import_boundaries.py` for `music_analyzer`, `test_music_explorer_boundaries.py` for `music_explorer`). They fail closed: a new standard-library import in an inner layer needs a deliberate allowlist change and boundary review.

### Directory Structure

```
<package>/                     # music_analyzer/ and music_explorer/
├── domain/                    # Business rules: entities, value objects, invariants. Pure, no I/O.
├── application/
│   ├── use_cases/             #   One directory per use case, named for user intent (scan_library/, build_graph/, generate_playlist/)
│   ├── ports/                 #   Interfaces the use cases need (repositories, audio, clock…)
│   └── dto/                   #   Plain data crossing the boundary
├── interface_adapters/        # Presenters, controllers, mappers: translate between use cases and the outside
├── infrastructure/            # Details: SQLite persistence, FFmpeg, Essentia, filesystem, environment
└── frameworks/                # CLI entry points, the Explorer web server and assets, composition root
    ├── cli/
    └── explorer/

tests/
├── unit/                      # Fast, framework-free: domain, application, adapters, tools
├── integration/               # Real SQLite and other infrastructure at the boundary
├── acceptance/                # CLI, HTTP and Explorer behaviour end to end (browser modules are opt-in)
├── architecture/              # Dependency Rule checks
└── support/                   # Shared synthetic fixtures
tools/                         # Public-safe diagnostics, benchmarks and the browser gate; not shipped
docs/                          # Reference and policy documents
plans/                         # Longer-term plans
```

Rules for the structure:

- **Screaming Architecture.** Name modules and directories for the domain concept or user intent they serve (`analyze_batch`, `playlists`), never technical kinds (`services`, `helpers`, `utils`, `manager`).
- **One use case per directory** in `application/use_cases/`. Each holds its interactor, its request and response models, and its output boundary (the presenter port). Use cases don't call each other; share policy through the domain or a port. Existing single-module use cases move into directories as they are touched.
- **Unit tests mirror the source**, directory for directory: the tests for `music_explorer/domain/energy_plan.py` live in `tests/unit/music_explorer/domain/test_energy_plan.py`. Existing tests move as they are touched.
- **Ports live with the inner layer that owns them.** Never put an interface next to its only implementation in an outer layer.
- **Data crossing a boundary is a simple data structure** defined by the inner layer. Never pass SQLite rows, HTTP requests or JSON payloads inward, or entities outward.
- **New boundary = new directory.** Code in a directory that doesn't respect its boundary is in the wrong place: move it.
- **Frameworks are details.** SQLite, Essentia, FFmpeg, the HTTP server and the browser UI are plugins to the business rules.
- **Both Explorer asset copies stay identical.** `music_explorer/frameworks/explorer/assets/` and `music_analyzer/frameworks/explorer/assets/` ship the same `app.js`; change both, and tests run against both.

### The Explorer Browser App

The frontend is held to the same standard as the backend: Clean Architecture as Uncle Bob would write it, with the folder structure as the architecture. The browser app is a program in its own right. It is plain JavaScript as native ES modules, served as static assets with no build step and no runtime dependencies beyond the vendored Three.js. It is laid out by layer:

```
music_explorer/frameworks/explorer/assets/app/
├── domain/          # Pure rules: graph filters, selection, playlist recipe. No DOM, no fetch.
├── application/     # One directory per use case (load-graph/, select-track/, download-playlist/), plus ports/:
│                    #   ExplorerApi (the HTTP gateway), Clock
├── adapters/
│   ├── controllers/ #   DOM input → validated request models
│   ├── presenters/  #   response models → view models
│   ├── view-models/ #   plain data shaped for a view
│   └── gateways/    #   ExplorerApi over fetch
├── frameworks/      # The DOM views and the Three.js scene: details
└── main/            # Composition root: the only module that knows every layer; wires them and starts the app
```

- The Dependency Rule applies to `import` statements exactly as to Python imports. It is enforced by an architecture test in `tests/architecture/` that parses every module's imports and fails closed.
- **No global mutable state.** State lives in domain entities owned by the use cases. Views hold none.
- Domain and application modules are tested in Node (`node:test`) without a DOM or a network. Their tests mirror `app/` under `tests/unit/explorer_app/`.
- Both asset trees (`music_explorer/…/assets/` and `music_analyzer/…/assets/`) stay identical, file for file.
- The existing single `app.js` moves onto this structure as it is touched; new browser features go into the layered modules.

### Code Standards (Clean Code)

- **SOLID** throughout, especially SRP (one reason to change), OCP (add new kinds of analysis or playlist rules without modifying existing ones) and DIP (depend on abstractions at every boundary).
- **TDD.** Follow the three laws: write a failing test first, write only enough test to fail, write only enough code to pass. Red → Green → Refactor. A bug fix starts with a test that reproduces it, and the regression test stays. Mechanical changes (formatting, renames, moves) are the only exception.
- **Test behaviour, not implementation details.** Domain and application tests use fakes, stubs or in-memory adapters for ports and run without a database, network, browser or framework. Slow infrastructure tests never replace them.
- **Names reveal intent.** Use the listener's and DJ's language (`Track`, `Playlist`, `MoodAxis`, `BpmRange`), not generic names (`Manager`, `Helper`, `Util`, `Data`, `Info`).
- **Small functions** that do one thing at one level of abstraction. Few arguments (ideally ≤ 2; no boolean flag arguments).
- **No comments that explain bad code.** Refactor until the code explains itself. Comments are for *why*, never *what*.
- **No side effects hidden in queries**; separate commands from queries. No global state, no hidden I/O.
- **Boy Scout Rule:** leave every file cleaner than you found it.

### Before Adding or Moving Code

1. Identify the use case or business rule, and decide which layer the code belongs to (entity rule, use case, adapter or detail).
2. Put it in that layer's directory, under the concept or use case it serves.
3. Check every import against the Dependency Rule. If an inner file needs an outer thing, declare a port in the inner layer instead.
4. Write or update the test first, then run the relevant tests and the architecture checks.

If requirements are unclear, ask before inventing architecture. Don't introduce frameworks, databases, queues or external services unless the task requires them or the project already uses them.

### Choosing What to Work On

**Bugs before features.** Fix known bugs before starting feature work. Bugs include:

- open bug tickets;
- failing or flaky tests;
- a bug found along the way.

Pick up a feature only when no known bug is waiting. A bug found while building a feature gets a ticket straight away, ahead of the next feature.

### Before Picking Up a Ticket

A ticket describes a problem as it stood when it was written; the code may have moved on.

1. Check it against main first, writing no code: what's already done (the docs, the tests, later comments), whether the files and names it gives still exist, and which changes came after it.
2. Comment on the ticket what's done, what's left and where it lives now ("Checked against main at `<sha>`: …").
3. Its suggested locations and approach are hints. This file's architecture wins: where they clash, follow the architecture and say so in the PR.
4. Where what's left needs an owner decision rather than code, ask on the ticket and move on to the next item; never guess.

## Commands

Run from the repository root with the project's virtualenv active (`python -m pip install .`).

```bash
python -m unittest discover -s tests/unit -v                     # fast unit tests
python -m unittest tests.architecture.test_import_boundaries tests.architecture.test_music_explorer_boundaries -v   # Dependency Rule
RUN_FFMPEG_TESTS=0 RUN_PACKAGING_TESTS=0 python -m unittest discover -v   # full suite, as CI runs it: before every PR
RUN_FFMPEG_TESTS=1 python -m unittest tests.integration.infrastructure.test_audio_decode -v   # opt-in real FFmpeg decode
python -m tools.explorer_browser_gate prepare --wheelhouse <dir>   # build the offline wheelhouse for the browser gate
python -m tools.explorer_browser_gate run --wheelhouse <dir> --evidence <dir>   # every Chromium module, installed wheel, under Podman
python -m tools.explorer_browser_diagnostic --real-browser ...     # descriptive browser timings; see docs/explorer-browser-diagnostic.md
music-analyzer --database "$DB" <command>    # scan, analyze, list, show, override, export, graph build, integrity…
music-explorer --database "$DB" --port 8765  # the read-only Explorer at http://127.0.0.1:8765/
```

Opt-in test switches: `RUN_FFMPEG_TESTS=1` for real decode, `RUN_BROWSER_SMOKE=1` and the other `RUN_EXPLORER_*` variables for Playwright/Chromium modules. Run browser modules through the gate, not ad hoc. `test_integrity_d1_installed` needs a `setuptools>=77` wheel in `/usr/share/python-wheels`; without it, it errors locally for that reason alone.

CI: `.github/workflows/ci.yml` runs the unit and architecture tests, a dedicated real-SQLite check, then the full suite with real decode and packaging disabled, on Python 3.14.8. FFmpeg integration runs only on a manual dispatch. CI is not installed-wheel or real-browser evidence: for Explorer UI changes, also run the browser gate and report its result.

Pull requests: branch from main, keep each PR small and reviewable, report what changed and which tests ran (including SKIP and BLOCKED results, never hidden), and document any architectural trade-off in the PR. Merge only with CI green.

`tools/` holds public-safe diagnostics, benchmarks and the browser gate. They sit outside the layers: the packages never import them, and their tests live in `tests/unit/benchmark_tools/`.

## Definition of Done

A change is done only when:

- its behaviour is covered by tests, written first;
- the tests and the architecture checks pass;
- dependencies point inward and folder placement reflects the boundaries;
- domain and application layers are free of framework and infrastructure details;
- any architectural trade-off is documented in the PR and the final report.
