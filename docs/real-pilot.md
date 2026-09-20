# Bounded local real-runtime pilot — 2026-09-20

This is execution validation, **not calibrated accuracy, listening evaluation,
representative Phase 5 acceptance or release acceptance**. Fourteen user-approved
FLAC files (74.40 minutes, 174.83–450.51 seconds each) were used read-only; no
ratings were invented, no audio/metadata was uploaded. Before/after SHA-256 and
size inventories match for every file. Private paths/results remain outside Git.
The convenient collection is smaller than the planned 50–100-track stratified
pilot. No real user MP3/AAC collection or other platform was validated.

## Tested runtime (optional, not a default dependency)

Linux x86_64, Arch kernel 7.1.9, Python 3.14.7, AMD Ryzen AI MAX+ 395, 94 GiB
RAM. A fresh external user venv used binary wheels only:

```
essentia-tensorflow==2.1b6.dev1438
numpy==2.5.3
PyYAML==6.0.3
six==1.17.0
```

Install this exact experimental combination with `pip install --only-binary=:all:`
in an isolated Python 3.14 venv; do not assume wheels exist for other combinations.
The Essentia wheel was 291.9 MB, NumPy 16.7 MB; no separate TensorFlow, NVIDIA
packages, system Python changes, source compilation or GPU stack was installed.
Essentia reports `2.1-beta6-dev`; package version above is more specific. Its bundled
TensorFlow emits missing CUDA runtime/no-device diagnostics but CPU inference
succeeded. Setuptools 84.0.0 was installed only for packaging tests.

All six approved graphs (~28 MiB total) were downloaded via `models download`
into `~/.local/share/music-analyzer/models`; initial HTTPS handshake timeouts
resolved on two explicit retries. `models verify` passed all bundles. Receipts
contain local SHA-256, not publisher-authenticated checksums. Publisher licensing
ambiguity remains: this validation grants no commercial or derivative permission.
`doctor` still intentionally reports `analysis_ready: false`; availability and
this one tested host do not establish general readiness.

## Real inference and regressions

First single-track run completed BPM/key but failed genres: native Essentia
rejects tuple-of-tuples as MATRIX_REAL. A deterministic red test preceded the
adapter-only fix converting immutable cached embeddings to nested lists at the
native boundary. Rerun completed all six stages. Real export then exposed a
floating-point duration reconstruction error (324.16 reconstructed as
324.15999999999997). A red round-trip test preceded a narrowly bounded roundoff
correction in the persistence mapper; material inconsistencies remain rejected.
Domain rules/dependency direction are unchanged. No stored evidence was edited.

A separate cold-cache instrumented real run captured actual native tensors:

| Graph/output | Per 30-second section shape |
|---|---|
| Discogs EffNet `PartitionedCall:1` | 30 × 1280 embeddings |
| Discogs400 `PartitionedCall:0` | 30 × 400 scores |
| Jamendo mood `model/Sigmoid` | 30 × 56 scores |
| Jamendo instrument `model/Sigmoid` | 30 × 40 scores |
| MSD MusiCNN `model/dense/BiasAdd` | 20 × 200 embeddings |
| Emomusic `model/Identity` | 20 × 2 scores |

Persisted label order matches the bundled official metadata for all semantic
results, including Emomusic **valence, arousal**. Shapes and finite outputs were
validated, not semantic correctness of class assignments. Native preprocessing
used mono 44.1 kHz decoded PCM, 16 kHz resampling for semantic models, native
repeat-final-patch framing. Scores remain raw, uncalibrated, with no energy scale.

## Bounded measurements and outcomes

One worker, CPU affinity 0–3, OMP/OpenBLAS/TF intra/inter-op thread limits 1,
CUDA disabled. External subprocess monitor sampled session/process descendants'
RSS every 250 ms; summed RSS can double-count shared pages and miss short peaks.
A 30-minute watchdog bounded each invocation. No concurrent analysis workers.

- Batch: 14 attempted, 14 completed, zero failed; 124.04 seconds wall,
  35.99 audio-seconds/wall-second, 6.77 tracks/minute.
- Batch sampled peak RSS: 913,948,672 bytes (~872 MiB). Includes startup/model
  loading, decoding and persistence. One track had reusable embeddings from the
  initial run; other 13 were embedding-cache cold. OS cache was uncontrolled.
- Explicit cold-embedding single-track probe: 9.11 seconds, sampled peak
  724,013,056 bytes; warm-cache probe: 3.89 seconds, 449,220,608 bytes.
- BPM/key use whole audio. Semantics use three disjoint 30-second sections per
  track: 1,260 / 4,464.04 seconds (28.23% collection exposure); per-track coverage
  19.98–51.48%. Overlapping/padded patches are not extra independent coverage.
- JSON/CSV exports and stored-stage validation succeeded after the mapper fix.
  An external SQLite backup passed integrity check (restore not rehearsed).
- 144 tests passed with real generated FFmpeg decode fixtures and packaging
  enabled, including boundary/CLI tests. Generated MP3/AAC/FLAC fixtures validate
  decoding, not six-stage inference on those formats.

Peak temporary disk was not measured; final cache/DB/temp sizes are retained.
Timing is not a library extrapolation, per-stage benchmark, interruption/recovery
acceptance or controlled offline/network-isolation test. Inference code did not
invoke downloads or external services. Mixxx remains untouched and out of scope.

Private evidence root:
`~/.local/state/library-analyser-delivery/real-pilot-20260920-200329/`.
It contains original failure/raw outputs, batch IDs, tensor probes, model receipts,
wheel hashes/versions, resource logs, exports, database/backup, before/after
inventories, red/green tests and revision-bound final report. Embeddings are under
`~/.cache/music-analyzer-real-pilot{,-cold}/`; weights are not in the repository.
Independent review, licensing clarification, representative listening/calibration,
broader recovery and final release gates remain open.
