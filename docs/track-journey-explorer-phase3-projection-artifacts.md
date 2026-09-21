# Track Journey Explorer Phase3 projection and artifact contract

This document freezes the Phase3 deterministic projection baseline before
production implementation. It is intentionally boring, stdlib-only and
reproducible. It is **not** PCA, t-SNE, UMAP, embeddings, calibrated affect axes,
a browser/API contract, or a claim that screen distance is musically meaningful.

## Version strings

- `projection_policy_version`: `anchor-distance-projection-v1`
- `projection_feature_contract_version`: `projection-features-v1`
- `projection_artifact_version`: `journey-projection-artifact-v1`
- `projection_fingerprint_version`: `projection-fingerprint-v1`
- `projection_refresh_policy_version`: `fixed-transform-refresh-v1`
- `neighbour_policy_version`: `bounded-symmetric-neighbours-v1`

Artifacts must store these strings and loaders must reject unknown versions with
an actionable error. Reproducibility metadata records the Python implementation
version and, when available, source revision information without assuming that
`git` is installed.

## Input feature groups

Projection inputs are derived from the Phase2 explorer snapshot after manual-text
precedence has been applied. Manual override text is unresolved: it is preserved
for display but is not converted into numeric projection evidence.

The baseline may use only these compatible evidence groups:

1. `tempo`: finite positive `bpm` from automatic values.
2. `energy`: finite `arousal` from the `energy` summary values.
3. `mood`: finite summary label scores from a compatible mood model/label set.
4. `genre`: finite summary label scores from a compatible genre model/label set.
5. `harmony`: parseable conservative key value supported by Phase2 harmony rules.

Raw source values remain available in explorer/candidate responses. Coordinates
and neighbour edges never replace or mutate raw feature evidence. Candidate
ranking continues to use the Phase2 ranking policy and must not use projection or
screen coordinates as inputs.

## Compatibility and missing evidence

A feature group is supported for a track only when all values needed by that
group are finite and compatible with the fitted transform.

- Label vectors are compatible only when the label set and model/provenance key
  match the transform group metadata exactly. Different labels or model strings
  are missing evidence, not maximal distance.
- Zero label vectors are missing usable evidence because cosine distance is not
  defined.
- Unparseable, ambiguous, or manually overridden keys are missing harmony
  evidence.
- Non-finite numbers, non-positive tempo, absent runs, failed runs, unresolved
  manual text, and absent fields are missing evidence.

Missing groups must not fabricate meaningful positions. Every projected track
therefore carries a `layout_state`:

- `projected`: at least one compatible anchor-distance group contributed.
- `partial`: some compatible groups contributed and some fitted groups were
  missing; coordinates are computed from supported groups and missing groups are
  disclosed.
- `missing`: no compatible fitted group contributed; `x` and `y` are `null` and
  no neighbour edges are emitted for that track.
- `degenerate`: the fitted transform had no usable range for a coordinate; the
  coordinate falls back to `0.0` and the degenerate axis is disclosed.

No unexplained id jitter is allowed. Tie-breaking and fallback ordering use the
stable track id lexicographically.

## Anchor selection

Fitting a transform chooses fixed anchor feature values from the snapshot and
persists them in the artifact. Refresh uses these persisted anchors; it does not
refit unless the caller requests explicit relayout.

For each supported feature group:

1. Build canonical comparable values for tracks with usable evidence.
2. Select a `low` anchor track and a `high` anchor track by the group-specific
   scalar below. Ties are broken by track id.
3. Persist the anchor track ids, raw anchor feature values, group model/label
   compatibility metadata, and scalar values.

Group scalars:

- tempo: `log(bpm)`.
- energy: raw `arousal`.
- mood: first principal label is **not** computed; use the lexicographically
  first compatible mood label score as the scalar for anchor selection.
- genre: use the lexicographically first compatible genre label score as the
  scalar for anchor selection.
- harmony: use conservative circle-of-fifths semitone index for parseable keys.

If a group has fewer than two distinct finite scalar values, the group is marked
`degenerate` and may contribute disclosure but not meaningful range.

## True feature distances

Neighbour edges use symmetric true-feature distances, separate from directional
ranking. For a pair of tracks, each compatible supported group contributes a
distance in `[0, 1]`:

- tempo: `min(1, abs(log(bpm_b / bpm_a)) / log(2))`.
- energy: `min(1, abs(arousal_b - arousal_a) / 2)`.
- mood and genre: cosine distance `1 - cosine(vector_a, vector_b)` over the
  fitted compatible label set, clamped to `[0, 1]`.
- harmony: `0` for same key, `0.25` for relative major/minor, `0.5` for same
  tonic different mode, otherwise `min(1, fifth_steps / 6)`.

The pair distance is the weighted mean of supported group distances. Unsupported
groups are skipped and their missing reasons are disclosed. If no group supports
a pair, there is no edge and no fabricated maximal distance.

## Projection formula

For every track and non-degenerate fitted group with compatible evidence:

1. Compute `d_low`, the true feature distance to the persisted low anchor.
2. Compute `d_high`, the true feature distance to the persisted high anchor.
3. Convert to a signed anchor-difference contribution:
   `contribution = d_low - d_high`.

The raw horizontal coordinate is the weighted mean of tempo, energy and harmony
contributions. The raw vertical coordinate is the weighted mean of mood and genre
contributions. If an axis has no contributing group, that axis is `null` unless
the artifact explicitly marks the axis degenerate, in which case it is `0.0` with
disclosure.

Fitting stores `center_x`, `center_y`, `range_x`, and `range_y` from raw projected
coordinates with non-null values. Display coordinates are:

`x = clamp((raw_x - center_x) / range_x, -1, 1)`
`y = clamp((raw_y - center_y) / range_y, -1, 1)`

`center` is the median raw coordinate. `range` is the maximum absolute deviation
from the center. A zero or missing range marks that axis degenerate and yields
`0.0` only for tracks that otherwise had evidence on that axis. Tracks with no
evidence remain `missing` with null coordinates.

## Neighbour graph

The artifact stores a bounded sparse graph, never a dense matrix and never an
unbounded retained pairwise matrix. Default `k` is `10`.

For each track, compute exact symmetric true-feature distances to a bounded,
deterministic candidate window in cheap scalar order as a streaming calculation.
The Phase3 utility is an exploratory sparse baseline, not an exact all-pairs
nearest-neighbour index. For the undirected exported graph, an endpoint must have
degree `<= k`; when proposals would exceed the cap, retain edges sorted by
`(distance, min_id, max_id)` while respecting both endpoint caps.

Edges require at least one supported group. If no group supports a pair, omit the
edge and record a missing/no-edge reason in diagnostics.

## Fingerprint

The projection artifact fingerprint is canonical JSON with sorted keys and no
incidental whitespace. It includes only safe, reproducible identity and policy
inputs:

- artifact and policy version strings;
- schema/application ids from explorer metadata;
- sorted track identities: `track_id`, `sha256`, `size`, display label, available
  location count;
- safe automatic evidence values, summary values, coverage, uncertainty, and
  provenance/model labels needed for compatibility;
- manual override field names and manual text hashes/markers sufficient to know
  unresolved manual text exists, not raw private paths;
- projection parameters including group weights, `k`, and explicit relayout flag.

It must exclude raw `run.detail`, private file paths, raw predictions, source DB
paths, artifact output paths, timestamps, process ids, dictionary insertion
order, and non-canonical float spellings. Equivalent snapshots must produce the
same fingerprint regardless of input order.

## Artifact preparation and replacement

Preparation reads one coherent readonly explorer snapshot through the application
port, fits or refreshes the transform, validates the full candidate artifact, and
then asks the artifact store to replace it atomically.

The filesystem store writes to a temporary file in the artifact directory,
flushes and fsyncs the file, validates by reading the temporary artifact back,
renames it over the old artifact atomically, and fsyncs the directory when the
platform supports it. The source catalogue/database location is never used as the
artifact path and must never be overwritten.

Validation rejects:

- unknown artifact/version strings;
- invalid JSON or missing required keys;
- non-finite coordinates/distances;
- coordinate shape errors;
- duplicate track ids;
- edges referencing unknown tracks;
- endpoint degree greater than `k`;
- dense `N x N` matrices or retained unbounded pair arrays;
- artifacts exceeding the configured resource limits.

On any preparation, validation, write, or rename failure, the previous artifact
is preserved.

## Load and refresh

Browsing load is read-only. It loads and validates the artifact or returns an
actionable failure such as `missing`, `corrupt`, `unsupported_version`,
`fingerprint_mismatch`, or `resource_limit_exceeded`. Load never repairs,
rebuilds, refreshes, or writes an artifact.

Refresh compares the new snapshot fingerprint with the artifact transform:

- If transform versions, parameters, anchors and compatibility metadata match,
  unchanged tracks keep identical coordinates and neighbour tie ordering.
- Added or changed tracks are projected through the persisted transform.
- Removed tracks disappear from the result and their edges are dropped.
- Explicit relayout is the only operation that refits anchors, centers, and
  ranges.

Candidate snapshot coherence uses the same readonly adapter boundary as Phase2;
application and domain code do not import filesystem, SQLite, CLI, or framework details.

## Minimal preparation CLI

Phase3 exposes only a local preparation composition command:

```bash
music-analyzer prepare-projection --database /path/to/analysis.sqlite \
  --artifact /path/to/safe/projection.json --k 10 --json
```

Use `--refresh` to reuse the persisted transform and keep unchanged coordinates
stable. Use `--refresh --relayout` only when the operator explicitly accepts a
new fit of anchors, centres and ranges. This command does not start a browser,
API server, inference, cache reconstruction, scan, migration, source database
write or model download.

