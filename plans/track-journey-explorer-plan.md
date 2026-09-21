# Track Journey Explorer — implementation plan

## 1. Status, approval and delivery order

This is a **planning document, not implemented behavior or release acceptance**.
It is grounded in the current CLI at `92feb298bdf14a996e045aad2724dbfa383f8102`
on `feat/phase-one-setup` (PR #1). It supplements, rather than declares completion
of, [the CLI plan](music-analyzer-cli-plan.md).

The required order is:

1. Commit this plan only to the existing PR branch.
2. Arrange a **fresh adversarial review of the current PR**, including this plan,
   against the exact pushed revision. This writing task is not that review.
3. Address review findings and let **the user merge PR #1**. No agent merge is
   authorized by this plan.
4. Only after that merge and an explicit next-feature go-ahead, begin the phased
   explorer work on a new feature branch. Do not implement it in this PR.

An isolated review environment is currently blocked by a harness read-only nested
mount issue; this is a review-infrastructure blocker, not evidence of approval.
The parent arranges review separately. Do not substitute a self-review or claim
that a pending review has passed.

## 2. User intent and scope

Build a local browser-based interactive **3D graph for live next-track selection**.
The user manually identifies the current track while DJing elsewhere, explores
compatible directions, inspects a ranked list and deliberately chooses the next
track. This is decision support, not playback, an automatic playlist generator or
an asserted guarantee of a good transition.

A typical journey:

1. Open a prepared local catalogue snapshot; see its age and evidence warnings.
2. Search/select a track and explicitly **Set as current**. Merely inspecting a
   node must not change the current track or history.
3. Combine energy direction, moods, genre exploration, tempo and harmonic
   controls. Keep every enabled control visible; changing one never resets another.
4. Inspect eligible neighbours in the graph and the same results in a ranked,
   keyboard-accessible list. Read why each candidate ranks and what is unknown.
5. Choose a candidate and explicitly confirm it as current. Append that selection
   to session history and continue. The user may choose a different track manually.

The graph supplies orientation; the list is the dependable selection surface in a
live setting. Show a persistent current-track anchor, active constraints, candidate
count and uncertainty status. No setup, analysis or layout refit may unexpectedly
interrupt that flow.

### Explicit exclusions

- Playback, preview audio, transport controls, automatic detection of the playing
  track, streaming, recording, DJ-controller integration or automatic queueing.
- Mixxx reads/writes or control, beat alignment, beat-grid correction, phase sync,
  cue/phrase matching, transition execution or promises of mixability.
- Audio-tag edits, library rescanning or inference from the browser/API; automatic
  model downloads, background watching, cloud hosting, telemetry or external APIs.
- Training new models, declaring calibration from the present sample, acoustic
  duplicate detection or equating different encodings with the same recording.
- Building this next feature, adding dependencies, migrations or a server as part
  of the current plan-only change.

## 3. What exists: source-grounded data and durability audit

Read `AGENTS.md`, the existing plan, `README.md`,
[real-pilot.md](../docs/real-pilot.md), [release-preparation.md](../docs/release-preparation.md)
and the source below. Repository schema/code inspection is not an inspection of a
private deployed database; a read-only check of the chosen real database remains a
phase-1 gate.

| Existing source | Observed capability and consequence |
| --- | --- |
| `domain/catalogue.py` | Track IDs are SHA-256 exact-file identities; separate locations may share one identity. Do not merge recordings by name or path. |
| `infrastructure/persistence/analysis.py` | Application ID `0x4D414E41`, schema v4; tables `runs`, `stages`, `tracks`, `locations`, `scan_roots`, `batch_jobs`, `run_tracks`, `overrides`. Stage evidence is JSON, not a feature-vector table. No projection, neighbour index or session-history schema exists. |
| Same repository | Construction can create/migrate schemas; read operations use `BEGIN IMMEDIATE`. **Do not reuse this concrete repository as a read-only HTTP backend.** Build a genuinely read-only adapter behind a query port. |
| `application/dto/review.py`, `application/use_cases/review.py` | Identity-linked review snapshots, raw/effective values, missing-evidence reasons and override precedence exist. Latest linked run is selected, including failed/incomplete runs; legacy path-only runs are not attributed. Never silently fall back to older completed evidence. |
| `infrastructure/persistence/stage_mapping.py` | Stored stages retain labelled summaries, windows, raw predictions and provenance; existing finite/shape/coverage checks are useful mapping precedent, not proof of a complete feature contract. |
| `domain/analysis.py`, `infrastructure/analysis/essentia.py` | Duration-weighted sampled semantic summaries; BPM/key are whole-track estimates with unresolved ambiguity. Energy is raw arousal with valence retained, **not a DJ energy scale**. |
| `domain/review.py`, `overrides` table | Overrides are nonblank free text, up to 4096 characters, not typed BPM/key/energy/genre data. They take precedence for display and survive reanalysis, but there is no override audit history. |
| `application/use_cases/reuse_embeddings.py`, `infrastructure/analysis/embedding_cache.py`, CLI cache wiring | Shape-validated section tensors are stored in a disposable JSON cache under XDG cache, normally `music-analyzer/embeddings-v1`. Entries have digest checks, atomic replacement, a 16 MiB entry bound and 256 MiB directory target after successful writes, with oldest-write eviction. Concurrent writes can exceed the bound; cache errors become misses. This is **not durable catalogue embedding storage**. |
| `infrastructure/analysis/essentia.py` | Cache keys include audio identity, embedding model hash/metadata, runtime/NumPy version, preprocessing, algorithm source digest, regions, rate and duration. Classifier heads share compatible embeddings; the head identity is intentionally excluded. The filename is a key digest, not a queryable track-to-vector index. |

Raw prediction matrices persisted in `stages` are **classifier outputs, not the
original embeddings**. The 14-track pilot observed Discogs EffNet 1280-wide and
MusiCNN 200-wide section embeddings, but those observations do not establish a
stable whole-track similarity vector contract. Cache deletion or eviction must not
make the explorer invoke inference or silently switch its distance definition.

**Proposed first baseline:** derive compact features from retained, validated
stage summaries/windows and recognized overrides. Do not require cached embeddings
for first delivery. In phase 1, compare that baseline with optional pooled
embeddings only if a measurable retrieval benefit justifies the extra storage and
preparation. Before proposing embedding reuse, verify actual availability, key
reconstruction, model compatibility, pooling, section coverage, retention and
rebuild costs on an approved database copy. If adopted later, materialize a
versioned, provenance-bound derived artifact in durable application data through
an explicit preparation command; do not relabel the evictable cache as durable.

Reuse DTO concepts and pure policies where appropriate, not CLI rendering, its
mutable repository constructor or exports containing private paths wholesale.
Absent artist/title metadata must be shown honestly; filenames are untrusted
optional display labels, not invented metadata.

## 4. Selection policy: additive controls and honest explanations

Each control has an explicit mode: **off**, **hard requirement**, or **soft
preference**, with its threshold/range/weight displayed. Controls are simultaneous
and additive, not mutually exclusive exploration modes.

- **Energy:** hold, rise, fall or target a band relative to current; initially
  expose raw arousal/provisional relative intensity, not a fabricated 0–100 scale.
- **Mood:** multi-label preferences or exclusions; distinguish raw model evidence
  from a user assertion. Define within-control any/all semantics explicitly.
- **Genre exploration:** stay near, move toward named genres, or prefer novelty
  within an allowed distance band. Exploration never bypasses other hard rules.
- **Tempo:** explicit BPM band or relative tolerance. Half/double-time matching is
  opt-in, visibly marked and never evidence of beat alignment.
- **Harmonic compatibility:** versioned, named major/minor-key relation policy;
  show supported relations and ambiguity. No key estimate guarantees compatibility.

Across controls, hard filters **intersect**. Within a multi-label control the user
can choose any/all; defaults must be visible. Soft preferences rank only eligible
candidates and never admit a hard-filter failure. Default to no automatic
hard-filter enforcement, nonnegative bounded weights and deterministic ID-based
tie breaks. Return the active policy/version with each response.

Missing evidence is not zero, a neutral mood, low energy or proof of compatibility.
A required field without usable evidence fails that hard requirement, with an
explicit reason. For soft ranking, compute only supported contributions, disclose
which are absent and expose evidence coverage separately; incomplete candidates
belong in a labelled insufficient-evidence tier below fully evaluable candidates
under the proposed default policy. If all requested evidence is absent, do not
invent a score. Validate and test the exact coverage/tiering rule before shipping.

Empty results show per-constraint exclusions, missing-evidence counts and a
combined-conflict explanation (counts need not sum because failures overlap).
Offer previews such as “widen tempo” or “make harmony a preference”; only an
explicit user action applies them. Never silently relax a filter. Zero/one-track
catalogues, no current track, stale evidence, unavailable locations and wholly
unanalyzed tracks must have useful states rather than blank graphs.

A candidate explanation includes contributing feature distances, target direction,
weighted ranking contributions, satisfied/failed rules, raw versus overridden
values, evidence coverage, run/model identities and uncertainty. A ranking score
is a **relative uncalibrated heuristic**, never a probability or confidence that
a transition will work. Include a concise explanation in the list and expandable
details rather than overwhelming live selection.

### Manual overrides and journey history

- Preserve existing manual annotations and their provenance distinction. Recognized
  typed values may replace automatic values for filtering/ranking under a
  documented parser/version. Invalid or ambiguous text stays visible and makes
  that feature unresolved; do not silently ignore it and rank by the automatic
  value. Do not guess delimiters, units or equivalence to model scores.
- Override editing remains in the existing CLI for the initial read-only explorer.
  An explicit snapshot refresh incorporates changes and displays the new revision.
  Typed override editing would be a separately approved write capability.
- Current-track choice, controls and ordered history live in browser session state,
  not in analysis tables. Default to memory with an explicit reset; tab closure
  loses history unless a later opt-in persistence decision is approved.
- Record confirmed choices, not hover/click inspection, as **user selections**, not
  verified playback. Support undo of the last selection and visible history.
  Excluding current/recently selected tracks is a visible toggle, not a hidden rule.
  A deliberate manual choice outside recommendations is allowed with the relevant
  rule warnings retained. It does not rewrite evidence or auto-relax constraints.

## 5. Versioned feature, distance and projection contracts

Specify independent versions for extraction/pooling, normalization, similarity,
ranking weights/controls and 3D projection. Persist their parameters with a
catalogue snapshot fingerprint covering track/run identities, evidence/model
provenance and overrides. Do not reuse incompatible artifacts.

1. **Feature contract:** label order and model identity, supported tempo/key forms,
   section aggregation/coverage, finite-value validation, missing masks and typed
   override semantics. Reject mismatched dimensions/models rather than comparing
   unrelated vectors. Keep separate groups so 400 genre dimensions do not swamp
   tempo or energy merely by size.
2. **Normalization:** fit only during explicit snapshot preparation, recording
   fit population, transform parameters, outlier clipping and constant-feature
   behavior. Compare fixed meaningful ranges with robust per-library scaling;
   choose and version a baseline after fixtures/listening, not because a 14-track
   min/max looks plausible. Library-relative position is not calibrated intensity.
3. **Distances:** compute group distances in the actual normalized feature space;
   evaluate bounded vector/cosine distances for semantic groups, tempo ratios for
   BPM (explicit octave alternatives) and a discrete supported-key relation table.
   Test zero vectors, missing groups, outliers and degenerate catalogues. Select
   exact formulas and default weights via a documented phase-2 decision, not a
   claim that these choices are already validated.
4. **Ranking:** apply hard eligibility first, then group-normalized soft terms for
   similarity, target direction and bounded exploration. Disclose supported weight
   mass and missing terms. Separate directional preference from symmetric
   neighbour similarity; an energy rise need not be reciprocal. Version defaults
   and preserve stable ties for the same inputs.
5. **Projection:** choose a deterministic baseline (evaluate seeded PCA against a
   nonlinear alternative only if needed), recording algorithm/library version,
   seed, fit IDs and transform. The 3D map is a lossy visualization, not ground
   truth or a calibrated axis system. Do not label arbitrary axes “energy/mood”.

**Never rank or choose neighbours using screen-space or projected 3D distances.**
Graph edges represent explicit feature-space neighbours and have bounded degree;
explain projection distortion. Controls change highlights/eligibility/ranking,
not coordinates. Maintain node positions and camera during a session. New data
appears only after an explicit refresh with a revision/change notice; preserve
coordinates for unchanged nodes where the chosen transform supports it. If refit
is necessary, offer an explicit re-layout rather than silent movement. Changing
weights may change neighbours without pretending the fixed map was reprojected.

## 6. Browser interaction and accessible fallback

Provide orbit/pan/zoom, search, focus-current, reset-view, node inspection and a
clear set-current action. Avoid a permanently animated force layout. Distinguish
current, selected, recommended, filtered and missing-evidence nodes with shapes,
labels and contrast as well as colour. Filtered nodes may be muted for context;
they must not look eligible. Limit rendered nodes/edges without limiting the
searchable and pageable eligible list; make truncation visible.

The ranked list and details support all selection tasks without WebGL, a mouse or
3D navigation. Require keyboard operation, visible focus, semantic controls,
screen-reader labels/status updates, reduced-motion behavior and no colour-only
meaning. Graph/list selection and explanations use the same response snapshot.
If WebGL fails or reduced-resource mode is chosen, keep the list fully functional.
Show loading/stale/error state without replacing the current track or silently
promoting a recommendation. Ignore outdated asynchronous responses after a newer
query, and retain controls across recoverable errors.

## 7. Clean Architecture and the read-only localhost boundary

Retain the established `music_analyzer/` layout rather than introduce a parallel
backend. Proposed responsibilities (names are planning contracts, not new APIs):

| Layer/path | Responsibility |
| --- | --- |
| `domain/` | Pure feature validity, typed override interpretation, eligibility, similarity/ranking and explanation rules; no NumPy, HTTP, SQL, browser or filesystem imports. |
| `application/use_cases/`, `dto/` | Load explorer snapshot, find candidate tracks, explain candidate and prepare derived snapshot; orchestrate injected ports using framework-free DTOs. |
| `application/ports/` | Read-only catalogue queries, derived-artifact reads/writes for separate preparation, optional feature-neighbour/projection computation contracts. No concrete engines constructed inward. |
| `interface_adapters/` | HTTP request validation/controllers and minimal public view-model mapping; never reuse private export payloads as API responses. |
| `infrastructure/persistence/`, dedicated projection/artifact adapters | Validated read-only SQLite access and safe derived-artifact loading; optional numerical libraries and filesystem implementation. |
| `frameworks/web/`, browser delivery, CLI composition root | Local server/static assets and dependency injection. Browser rendering/session state separated from backend policy. Server invokes use cases, not CLI subprocesses. |

Use small explicit ports, not speculative services. Pure arithmetic may stay in
domain; numerical projection/index libraries implement outer ports. Extend the
existing AST import-boundary tests, reviewing any standard-library allowlist
change explicitly. Test browser state transitions independently of rendering.

The server opens an explicitly selected existing analysis DB with SQLite
read-only URI semantics and query-only defense, validating application ID and
supported schema without creating, migrating, recovering jobs or acquiring a
write transaction. An unsupported/locked/corrupt database yields an actionable
error. Do not assume `immutable=1` is safe on a live changing database. Decide
between bounded consistent read transactions and an explicitly prepared consistent
snapshot; test WAL visibility and concurrent analyzer writes using disposable DBs.

The initial API serves catalogue summaries, details, positions and candidate
queries only. No endpoint for arbitrary paths, SQL, shell commands, scans,
inference, downloads, exports to server paths or override mutation. Current track,
constraints and recent IDs are bounded query inputs, not persisted server state.
Derived artifacts are prepared separately, explicitly and locally; serving them
never silently repairs or recomputes missing embeddings. Keep artifact writes
separate from the read-only server process and never migrate the analysis schema
just to store a layout.

### Privacy and security acceptance

- Bind loopback only by default; reject public-interface binding for first delivery.
  Validate Host and Origin against the actual local origin to resist DNS rebinding;
  no wildcard CORS. Use a per-launch capability token, kept out of logs/URLs where
  feasible, and test hostile remote-page requests. Loopback alone is not authorization.
- Bundle scripts/fonts/assets locally; no CDN, telemetry, remote models or outbound
  requests during operation. Define a restrictive CSP and disable caching of
  sensitive API responses. Render all names/annotations as text, not HTML.
- Return opaque public handles/display labels, not full audio paths, private
  configuration, raw DB errors or bulk raw prediction tensors. Internal hash IDs
  need not be exposed as public identifiers. Serve only fixed bundled assets;
  reject traversal and arbitrary file access. No audio-file serving.
- Bound input lengths, weight ranges, page sizes, history IDs, response sizes and
  query concurrency; reject nonfinite/invalid inputs. Redact logs, avoid recording
  listening history and document local process/browser-user trust limitations.
- Test that browsing cannot modify DB rows/schema, audio, tags, Mixxx or models.
  Use disposable fixtures and file inventories, accounting separately for SQLite
  sidecars if an external writer runs. Preserve private `.quecto/` and `music/`;
  do not place private data, screenshots or artifacts in Git.

## 8. Resource and scaling experiment: proposed targets, not guarantees

Start with the intended approximately 3,000-track library and exact feature-space
ranking against one current track, avoiding a dense all-pairs matrix or an
all-node/all-edge browser payload. Use compact summaries, paged results, bounded
neighbour degree and an overview/viewport cap. Consider approximate indexing only
if measurements require it; compare recall against exact search and disclose the
tradeoff. No GPU or inference runtime should be required to browse prepared data.

The following are **proposed acceptance targets to confirm on the user's target
hardware**, not measurements or guarantees inherited from the CLI pilot:

| Workload | Proposed target and measurement |
| --- | --- |
| Prepared 3,000-track catalogue | Cold local open to usable list/map within 5 seconds; separately report process startup, artifact load and first render. |
| Repeated combined controls | p95 end-to-end list update within 200 ms over at least 100 scripted queries after warm-up; record p50/p95/max and cancellation behavior. |
| Graph interaction | At least 30 fps during a 30-second orbit with up to 1,000 rendered nodes and degree cap 10; keep the complete 3,000-track list accessible. |
| Memory/transfer | Proposed server peak RSS <=512 MiB, browser process increment <=512 MiB and initial compressed summary/layout transfer <=5 MiB at 3,000 tracks; state measurement tool and baseline. |
| Derived storage/preparation | Initial compact artifact budget <=100 MiB at 3,000 tracks; measure cold preparation time, peak RSS/temp disk and final bytes rather than promise unmeasured build time. Embedding materialization needs its own budget. |
| Growth and failure | Exercise 0, 1, 14, 3,000 and 10,000 synthetic tracks; report scaling curves, bounded paging, disk-full/missing-artifact recovery and degraded rendering/list-only behavior. |

Record hardware, OS, browser/version, feature dimensions, density, snapshot/recipe
versions and cold/warm definitions. Synthetic performance fixtures are not musical
quality evidence. If targets fail, first reduce payload/render density and add
paging; seek approval before changing scope or minimum hardware. Keep the CLI
usable without optional web/numerical dependencies.

## 9. Test-driven phases, dependencies and acceptance gates

Every production behavior change begins with a failing domain/use-case test,
then minimal implementation, then green refactoring. Adapter/browser tests follow
where the boundary requires them. No production code is authorized in this task.

### Phase 0 — merge and feature authorization

**Depends on:** this committed plan, fresh revision-bound adversarial PR review,
findings resolved and **user-performed merge**.

**Gate:** explicit approval to start the explorer; record unresolved decisions and
create its branch. Existing CLI/release gates remain open unless independently
satisfied; this plan does not mark any old milestone complete.

### Phase 1 — data contract and read-only vertical slice

**Depends on:** phase 0 and an approved disposable analysis snapshot.

Write failing tests for schema rejection, identity linkage, latest failed runs,
missing stages, free-text overrides and side-effect-free queries. Inspect actual
v4 schema/provenance and cache availability read-only. Decide summary baseline,
override grammar and durable derived-artifact strategy before proposing reuse.
Implement a narrow query port/adapter and framework-free explorer DTOs, then a
minimal list/detail boundary. No graph dependency is needed yet.

**Gate:** supported evidence maps without inventing data; unrelated/newer schemas
fail without changes; no initialization/migration/write transactions; DB/audio
inventories unchanged in the isolated fixture. Document stale-run and snapshot
consistency policy. Embedding absence is a supported state, not hidden inference.

### Phase 2 — feature policy and candidate selection

**Depends on:** phase 1's data/override contract.

Write failing tests for each control alone and combinations of all five, any/all
labels, hard intersections, directionality, missing evidence, unparseable overrides,
ties, zero weights, octave options and harmonic ambiguity. Implement versioned
normalization, exact feature-space distances, ranking and explanation DTOs with
fake repositories. Freeze formulas/defaults with rationale before UI integration.

**Gate:** soft scores cannot admit a hard failure; no-match reasons identify
conflicts without auto-relaxation; manual precedence holds; same versioned inputs
produce identical ranks; raw scores and uncertainty remain inspectable. Changing
projection coordinates cannot change rankings (explicit regression test).

### Phase 3 — stable layout and prepared artifacts

**Depends on:** phase 2's frozen feature contract.

Write failing tests for deterministic projection/artifact versions, invalidation,
constant/missing vectors, corrupt/missing artifacts and explicit refresh behavior.
Implement separate preparation and projection adapters; bounded true-feature
neighbours and fixed coordinates. Benchmark baseline exact search before adding
an index or optional embeddings.

**Gate:** filters/current-track/weights do not shift nodes; no dense graph payload;
positions/edges have clear provenance; stale artifacts are identified; browser
startup needs neither model loading nor cache reconstruction. Preparation failure
leaves previous valid artifacts intact and analysis evidence unchanged.

### Phase 4 — protected local API and interactive browser journey

**Depends on:** phases 1–3; confirm web/rendering dependencies and licensing first.

Start with failing API security/validation tests and browser session-state tests.
Wire the localhost composition root and bundled assets, graph/list parity,
set-current confirmation, combined controls, explanations, history/undo/reset and
keyboard-first fallback. Test rapid query changes, disconnected server, refresh,
WebGL failure and untrusted label text.

**Gate:** complete journey works without a mouse/3D, no inspection changes current,
no stale response replaces newer state, all controls remain additive, annotations
are read-only and history is not represented as playback. Host/Origin/token,
traversal/XSS, request limits, offline-assets and no-write acceptance tests pass.

### Phase 5 — live-use evaluation, scaling and hand-off

**Depends on:** phase 4, approved target hardware/library sample and user feedback.

Run fast units and architecture checks, SQLite/API integration, browser acceptance,
privacy/no-write checks and the measured workloads in section 8. Use a stratified,
user-reviewed sample to evaluate whether explanations and suggestions actually aid
live next-track choice. Record listening judgments and uncertainty separately
from model output; keep a holdout before changing defaults. Add failing regressions
for discovered defects; do not tune solely on the convenient 14 tracks.

**Gate:** publish revision-bound test/resource reports and known limitations,
confirm targets or renegotiate them explicitly, rehearse preparation/refresh/fallback,
and obtain user acceptance plus independent review of the implementation. Document
install/start/stop, local trust model, cache versus durable artifact cleanup,
session loss/reset and recovery. A polished map alone is not acceptance.

## 10. Evidence limits and remaining decisions

The existing pilot validated real execution on **14 approved FLAC tracks**,
74.40 minutes, on one host. Semantic exposure was 28.23% of that collection, with
19.98–51.48% per-track coverage. It did not supply listening ratings, representative
50–100-track calibration, transition judgments or explorer scalability evidence.
Whole-track BPM/key confidence/strength and semantic scores remain uncalibrated.
Raw arousal is not measured perceived DJ energy. Neither its inference throughput
nor its memory measurement predicts browser/API performance.

Before implementation decisions are locked, confirm: approved database snapshot
and hardware/browser; typed override grammar and energy presentation; exact
normalization/group metrics/default weights; projection choice/refresh policy;
read consistency with simultaneous analyzer work; dependency/license suitability;
and final performance budgets. Default to summary-derived features, in-memory
session history and read-only browsing. Any durable session history, annotation
editing or embedding inference is a separately reviewed expansion, not an implicit
consequence of this plan.

**Architectural tradeoff:** keep rich rules server-side behind application ports
and transient journey interaction in the browser. This costs a small local API and
explicit snapshot preparation but avoids duplicating ranking policy in rendering,
exposing private exports, coupling the domain to WebGL/SQLite or turning a live
selection tool into an analysis/write service.
