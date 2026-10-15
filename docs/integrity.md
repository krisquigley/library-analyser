# LIMITED offline integrity diagnostic (D3a)

```sh
music-analyzer integrity --database DB --json
music-analyzer --database DB integrity
python -m music_analyzer integrity --database DB --audit-deadline-seconds 30
```

A database path must be supplied explicitly. Repeated root/subcommand `--database` options (including `--database=DB`) select the **last explicit value in argv order**; earlier values are never opened. The command does not load Settings, default/XDG configuration, models, inference backends, FFmpeg, audio files, cache, graph builders or servers. Configuration/model and unrelated command options are rejected. It performs no migration or repair and does not change SQLite `user_version`.

## What D3a covers — and does not certify

D3a recognizes the existing application ID and true schema versions **6–10**, checks the exact existing FULL-reader schema contract (including its existing legacy tolerances), and examines every core track identity/digest/size and audio-policy row, including missing/orphan audio relationships. Both FULL readers and their trust behavior remain unchanged.

Every report exposes the finite twelve-check checklist: compatibility, schema, core_rows, metadata, retained_stages, current_graph, historical_graph, current_evidence, historical_evidence, sqlite_physical, sqlite_foreign_keys, resource_access. D3a adds metadata and retained stage payload checks. SQLite physical/foreign-key checks remain **not implemented**, deferred to D3b along with certification. D3a retains both graph checks and both compact evidence checks. Graph checks are genuinely not applicable in v6, and evidence checks in v6–8, only after trustworthy application/version recognition. Missing applicable coverage is never labeled not applicable. Schema drift can block dependent core checks.

Even a healthy v6 database returns `status=incomplete`, `complete=false`, `stop_reason=scope_not_implemented`, **exit4**. Core corruption findings remain visible but do not change that incomplete precedence. `implemented_scope_complete=true` means only the selected schema/core/metadata/retained-stage/graph/evidence work and resource cleanup completed; it can also be true when fully drained core scans found corruption. It is **not** P7 completion, a clean result, a trust token, or suitability for P8. No D3a invocation returns clean0/corrupt-complete1. #85's six-second case remains unresolved; no latency guarantee is made. #96 is separate, and P8 planning remains blocked until complete D3 diagnostics and separate exact-head writer parity are delivered.

Wire shape is `report_version=1`, capability is `coverage_revision=D3a`, and the finite promised checklist is `required_scope_revision=P7-1`. These fields do not change the package version or database schema version. Findings use fixed predicate codes and grouped occurrence counts, not distinct corrupt-track totals. Several findings can overlap on the same row; do not sum them as corrupt tracks. Completed counts are exact; interrupted counts/findings are lower bounds; blocked/unimplemented/N/A counts are unavailable, not fabricated zeroes.

## Metadata and retained-stage ownership

On every supported schema6–10, metadata examines every physical track_metadata row,
including inactive tracks, without a filtering join. Its three JSON documents are
parsed independently: malformed JSON contributes `metadata_json_invalid`; an
independently parsed malformed sibling can also contribute
`metadata_contract_invalid`. Common pairs require string keys and string or
sequence-of-string values; tags require string keys and sequence-of-string values;
warnings require a sequence of strings. Empty strings/keys/lists and duplicate keys
remain accepted. There is no mandatory title/artist, coercion, uniqueness/order rule
or metadata domain byte cap. Audio duration remains core-owned. Unreliable admitted
delivery contributes `metadata_delivery_invalid` and suppresses unreliable content
judgments.

Retained stages examine every physical stages row, regardless of run status,
currentness, track availability or stage name. Open/custom stage names remain
accepted. Successfully parsed objects use the established strict mapper and retained
validation without clearing raw predictions; successful mapping must agree with the
row stage. Optional windows/raw/summary and extra keys retain existing normalization.
Finite nonboolean numeric vectors and summary coverage **0<coverage<=1** are required;
window intervals retain existing ordering, disjointness, bounds and duration roundoff.
Nonempty unique labels are required only with windows. No new probability,
min/mean/max ordering, raw-summary agreement or original JSON container strictness is
introduced. Accepted empty outputs and negative/string estimates remain accepted.

The fixed ordered retained codes are `stage_json_invalid`, `stage_contract_invalid`,
`stage_identity_invalid`, `stage_payload_oversized`, `stage_delivery_invalid`.
Mapping failure blocks identity judgment. The fixed metadata code order is
`metadata_json_invalid`, `metadata_contract_invalid`, `metadata_delivery_invalid`.
Each code contributes at most one row-OR occurrence per physical row, not one per
component or defect. Codes may overlap; their sum is not a distinct-track total.

Both owners count one successfully observed bounded envelope per physical row,
even invalid or oversized; preflights/fragments/relookups do not inflate semantic
work. Exact counts require stream exhaustion and successful cursor cleanup. Empty
drained phases are exact0; interrupted work/findings are lower_bound including0;
unvisited applicable phases are blocked with unavailable/null counts. Previously
drained phases remain exact after later failures.

Stage domain admission is **inclusive16MiB decoded-document UTF8**, established
before fetching the whole payload. Metadata has no corresponding16MiB validity cap.
Runtime32MiB single-value and shared row/UTF8/group/deadline budgets still apply to
both. UTF16 TEXT/BLOB use incremental4096-byte storage decoding including embedded
NUL and split units; BLOB encoding/BOM handling follows json.loads, while TEXT BOM
is not stripped. A raw BLOB lone surrogate that cannot be strictly UTF8-sized yields
operational `read_error`, not stage/metadata corruption; an escaped JSON surrogate
continues through established content policy. Codec/read errors and MemoryError
are operational, not corruption evidence. No constant native scratch, linear-time,
hard wall-time or universal RSS guarantee is made.

These phases run in the displayed twelve-check order using the same pinned
read-only snapshot and shared operational meters as the other checks. They do not
change reader trust, writer policy, schema, graph/evidence derivation or P8 eligibility.
Healthy and corrupt supported databases both remain incomplete4/complete=false;
physical/FK completion is deliberately outside D3a.

## Graph ownership and counts

On v7+, current_graph checks the current pointer, current descriptors, current edges and their mirror relation. historical_graph checks all full builds (including current backing history), full-history edges and, on v8+, all positioned snapshots and edges. Established lifecycle/count/pointer/mirror/edge rules are diagnosed without changing FULL-reader tolerance, topology, eligibility, schema or package policy.

Both owners accept corruption codes `graph_lifecycle_invalid`, `graph_counts_invalid`, `graph_pointer_invalid`, `graph_mirror_invalid`, `graph_edge_invalid`. Occurrences are per invalid build for lifecycle; per invalid full-build/positioned descriptor for counts; per unequal full/positioned relation for mirror; and one OR-ed occurrence per bad edge row, even when several edge predicates fail.

Graph check counts represent semantic work, not all query deliveries: descriptors plus physical edge rows, excluding repeated preflights, mirror comparisons and lookups. The public two-build/one-edge fixture gives current/history **2/4** on v7 and **3/8** on v8–10. Empty drained graphs are completed with exact0; v6 graphs are N/A with unavailable/null counts. Every delivered SQLite row, including excluded semantic work, still charges the runtime row budget. Completion requires full streams and successful cleanup; healthy and corrupt supported graphs remain incomplete4/complete=false.

## Compact evidence ownership, predicates and counts

On genuine v9–10, every physical compact evidence row is checked, including inactive and old history. Numeric flag1 belongs to current_evidence; the disjoint remainder, including malformed/NULL flags if observed, belongs to historical_evidence. There is no requirement that every completed track/run has evidence or that every track has current evidence. Genuine v6–8 evidence is N/A with null/unavailable counts only after reliable recognition; unsupported/unrecognized input never earns N/A, and failed schema prerequisites block applicable evidence. Empty drained v9–10 evidence is completed0/exact, not unavailable. The public two-current/two-old fixture has semantic counts **2/2**.

Evidence semantic work counts one successfully observed bounded envelope per physical row, even if invalid or oversized. Link/latest/preflight/fragment/delivery lookups do not inflate this semantic count, but every delivered result row and decoded fragment charges shared operational budgets. Both phases must exhaust before selected-scope completion. Late failure retains the observed prefix: the interrupted phase's work/findings are lower_bound; earlier finished phases stay exact and unvisited applicable phases stay blocked.

The fixed ordered corruption codes accepted for either owner are:

| Code | Established predicate |
|---|---|
|evidence_envelope_invalid|Canonical FULL track identity, nonempty run identity, numeric flag membership0/1; one OR-ed occurrence per row|
|evidence_link_invalid|Completed referenced run, exact run_tracks pair, and current equals newest linked run by runs.rowid descending, even if newest run failed; duplicate-current exception is one occurrence per violating track|
|evidence_json_invalid|JSON decoding/parsing failure, parse recursion, or unsupported delivered scalar type|
|evidence_contract_invalid|Exact top-level object/keyset/version and identities equal row|
|evidence_feature_invalid|Exact five-stage/common shape, provenance/uncertainty, and established scalar/key/genres-without-summary contract|
|evidence_summary_invalid|Established genres/mood/energy summary-mode shape, finite vectors/labels, coverage0..1 and summary_values pairing|
|evidence_fingerprint_invalid|Lowercase64hex syntax or canonical decoded JSON SHA256 mismatch/encoding/recursion failure|
|evidence_delivery_invalid|Observed missing/duplicate/unexpected/mismatched admitted identity or impossible size metadata without a read exception|
|evidence_payload_oversized|Exact decoded-document UTF8 size exceeds inclusive16MiB; whole payload is skipped|

A code contributes at most one OR-ed occurrence per physical row, except the duplicate-current invariant's per-track exception. Independent envelope/link/size/fingerprint syntax defects may coexist. JSON requires successful admission/delivery; contract requires parse; child feature/summary predicates require appropriate parent shapes; canonical hashing requires valid content. Findings do not revalidate historical algorithms, inspect retained windows/raw predictions, recompute authenticity, or certify that an omitted evidence row should exist. BPM need only be finite (negative is not newly banned); summary coverage is inclusive0..1, with no invented min/mean/max ordering or probability rules. Existing JSON duplicate-key behavior and noncanonical stored whitespace/order remain accepted.

Fingerprint hashing uses canonical decoded JSON (sorted keys, compact separators, ensure_ascii=false, allow_nan=false) encoded UTF8, not stored-text bytes. BLOB JSON follows json.loads encoding detection, BOM handling and surrogatepass. A decoded raw BLOB lone surrogate cannot be strictly UTF8-sized: it yields fingerprint_invalid and skips content verdicts without claiming the JSON valid. An escaped surrogate reaches ordinary parsing and may fail canonical UTF8 hashing. SQLite TEXT delivery codec errors and MemoryError are operational failures, never inferred corruption.

## Evidence domain admission versus runtime resources

The writer's domain bound is **inclusive16MiB decoded-document UTF8**, independent of the **32MiB runtime single-value limit**. Exact oversize establishes payload_oversized before whole payload delivery and scanning may continue; a conservative runtime estimate is never corruption proof. A domain-valid value can still stop incomplete under runtime/shared budgets. BLOB byte-document BOM is excluded by decoding; a TEXT BOM is not stripped.

TEXT storage length in a UTF16 database is not UTF8 length. UTF16 TEXT and BLOB are preflighted using fixed4096-byte storage slices with incremental codec state and exact decoded UTF8 accounting, including embedded NUL and split code units/surrogate pairs; no character-length truncation at NUL and no full payload accumulation. UTF8 TEXT uses exact storage-byte admission. Every preflight/fragment/full delivery charges the shared budgets without resets. SQLite CAST/slicing may still allocate storage-sized scratch or repeat work: qualification fixtures do not prove universal constant memory or linear runtime. No hard wall-time/RSS guarantee is made.

## Safety, snapshot and work limits

The adapter uses an escaped SQLite URI with `mode=ro`, `query_only`, and an explicit BEGIN/first-read snapshot. No immutable shortcut, writer adapter, DDL/DML, migration, checkpoint or ATTACH is used. The report applies only to that pinned snapshot, finite checklist and diagnostic revision—not future/restored/external bytes or general database authenticity. It does not inspect audio files or authorize repair, backfill, or mutation.

Logical read-only is **not forensic sidecar immutability**: reading a WAL database may use SHM/read locks and pin WAL history. Back up the database with a SQLite-aware procedure; do not assume copying only the main file while a writer is active captures committed WAL state. Preserve required WAL/SHM sidecars consistently. If necessary, run against a safely produced offline backup rather than an actively changing library. The command does not checkpoint, merge sidecars, or create missing databases.

Default absolute cooperative deadline is120 seconds; `--audit-deadline-seconds N` accepts only finite positive values <=120. The deadline includes access and cleanup, with a remaining-time busy timeout and progress callback. Work stops also apply at1,000,000 delivered SQLite result rows,1GiB cumulative admitted UTF8 text,32MiB runtime single-value admission, and100 grouped findings. Scalar/preflight/descriptor/relation result rows and every evidence fragment count toward the delivered-row budget. Runtime caps mean incomplete work, **not new database validity rules**. Text/BLOB admission precedes full Python value delivery; exact evidence-domain preflight is separate from conservative runtime admission and storage bytes alone never prove corruption. Native SQLite preparation/allocation and Python work remain cooperative: no hard wall-time/RSS bound is promised.

All paths attempt cleanup. Deadline, caps, blocked dependencies, late read errors and cleanup failures keep selected-scope completion false. Cleanup failure overrides an earlier ordinary stop, while cancellation wins with exit130; already observed findings remain visible with appropriate precision. Findings are grouped by fixed check/code keys, capped at100; attempted excess groups set `findings_truncated=true` and stop incomplete rather than silently discarding observations.

## Exits and privacy

| Exit | Meaning |
|---|---|
|2|Invalid invocation; fixed sanitized stderr, no report and no target access|
|3|Unsupported application/version or initially unreadable/refused target|
|4|LIMITED D3a report, whether healthy, corrupt-observed, blocked, capped or late-error|
|130|Cancellation/SIGINT; incomplete report after attempted cleanup|

The first compatibility read can fail even after connection open; that remains an initially unreadable target (exit3), not late read failure. Operational deadline/caps before version recognition remain incomplete4, not unsupported3. Cleanup failure can supersede an unsupported result with incomplete4.

Text and JSON output are deterministic, sanitized fixed labels/codes/counts. They do not echo paths, configuration, SQL, database-derived object names, payloads, row samples, exception text or tracebacks. Unsupported raw schema versions are not echoed. Invalid integrity options do not echo supplied tokens or values. Output remains sensitive in the ordinary sense that counts and categorical findings describe the explicitly selected database; share it deliberately.

This diagnostic does not suggest automatic repair. Keep the source and a consistent backup, preserve evidence, and investigate findings separately; successful selected work is not permission to use omitted phases as trusted inputs.
