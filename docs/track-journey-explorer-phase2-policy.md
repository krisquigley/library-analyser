# Track Journey Explorer Phase2 candidate-selection policy

This document freezes the intentional Phase2 defaults used before any UI, graph,
projection, API or persistence work. They are conservative provisional policy
choices, not empirical DJ calibration.

## Version strings

- `feature_contract_version`: `summary-derived-v1`
- `override_policy_version`: `manual-text-display-only-v1`
- `selection_policy_version`: `candidate-selection-v1`
- `distance_policy_version`: `summary-distance-v1`
- `ranking_policy_version`: `additive-ranking-v1`
- `harmonic_policy_version`: `conservative-key-v1`

## Evidence and manual precedence

Manual override text remains display-only in Phase2. If manual text exists for a
field, the effective source is `manual_text`, typed status is unresolved, and the
automatic typed value is not used for filtering or ranking. Missing or unusable
evidence is not imputed as zero, neutral mood, low energy, compatibility or
incompatibility. Hard controls fail with explicit reasons; soft controls skip the
unsupported contribution and disclose missing evidence and weight mass.

## Controls, scoring and sorting

All controls default off. Enabled soft controls default to weight `1.0`; disabled
controls have weight `0.0`. Hard labels use an explicit provisional threshold of
`0.5` when the user enables that hard rule. A zero-weight soft control is valid
and produces deterministic eligible unscored candidates rather than a false
missing-evidence claim. Hard requirements intersect before soft scoring.

Soft contributions are bounded to `[0, 1]`. The score is:

`sum(weight_i * contribution_i for supported enabled soft controls) / sum(weight_i for supported enabled soft controls)`

Candidates with at least one supported positive-weight contribution are in
`eligible_scored`. Candidates that requested positive-weight soft controls but
have no supported contribution are in `eligible_insufficient_evidence`. When no
positive-weight soft controls are active, candidates are `eligible_unscored`:
that includes all controls off, hard-only policies that pass, and all-soft-zero
policies. Sorting is deterministic by scored tier, score, supported weight mass,
then track id. Projection or screen coordinates are never inputs to ranking.

## Distance/control decisions

- Energy uses raw `arousal` only for ranking; valence remains explanatory. Rise
  and fall are directional; hold and target-band use raw-unit tolerances.
- Mood and genre labels support explicit `any`/`all` semantics. Include soft score
  is the mean selected score; exclude soft score is `1 - max(excluded_scores)`.
  Partial missing labels are disclosed, not filled with implicit zeros.
- Genre vector distance aligns exact labels from compatible provenance/model
  evidence. Zero vectors or incompatible label/model alignment are missing
  evidence, not maximal distance.
- Tempo uses finite positive BPM and log-symmetric multiplicative tolerance. The
  hard threshold is `abs(log((candidate_bpm * multiplier) / current_bpm)) <=
  log(1 + tolerance)`, i.e. the accepted ratio band is `[1/(1+t), 1+t]`, not a
  literal additive +/- percentage. Half/double-time matching is opt-in and
  labelled by the selected multiplier.
- Harmony supports only same key and relative major/minor under
  `conservative-key-v1`. Ambiguous or unparseable keys are missing evidence. Key
  strength is explanatory only. Equal relation scores tie deterministically by
  track id.

## Application snapshot contract

Candidate selection consumes one coherent in-memory explorer snapshot from an
injected read port. Phase2 intentionally does not add a SQLite implementation,
cursor paging, graph/projection artifacts, browser/API/server behavior, writes,
inference, cache or embedding dependencies. The candidate pool is ranked before
applying the response limit; unsupported cursor semantics are rejected.
