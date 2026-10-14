# LIMITED offline integrity diagnostic (graph-only D2a)

```sh
music-analyzer integrity --database DB --json
music-analyzer --database DB integrity
python -m music_analyzer integrity --database DB --audit-deadline-seconds 30
```

A database path must be supplied explicitly. Repeated root/subcommand `--database` options (including `--database=DB`) select the **last explicit value in argv order**; earlier values are never opened. The command does not load Settings, default/XDG configuration, models, inference backends, FFmpeg, audio files, cache, graph builders or servers. Configuration/model and unrelated command options are rejected. It performs no migration or repair and does not change SQLite `user_version`.

## What D2a covers — and does not certify

D2a recognizes the existing application ID and true schema versions **6–10**, checks the exact existing FULL-reader schema contract (including its existing legacy tolerances), and examines every core track identity/digest/size and audio-policy row, including missing/orphan audio relationships. Both FULL readers and their trust behavior remain unchanged.

Every report exposes the finite twelve-check checklist: compatibility, schema, core_rows, metadata, retained_stages, current_graph, historical_graph, current_evidence, historical_evidence, sqlite_physical, sqlite_foreign_keys, resource_access. Metadata, retained stage payloads, evidence semantics and SQLite physical/foreign-key checks remain **not implemented**. Evidence on v9–10 is deferred to full D2; metadata/retained stages/physical/FK and certification are deferred to D3. Graph-only D2a is not full D2. Graph checks are genuinely not applicable in v6, and evidence checks in v6–8, only after trustworthy application/version recognition. Missing applicable coverage is never labeled not applicable. Schema drift can block dependent core checks.

Even a healthy v6 database returns `status=incomplete`, `complete=false`, `stop_reason=scope_not_implemented`, **exit4**. Core corruption findings remain visible but do not change that incomplete precedence. `implemented_scope_complete=true` means only the selected schema/core/graph work and resource cleanup completed; it can also be true when fully drained core scans found corruption. It is **not** P7 completion, a clean result, a trust token, or suitability for P8. No D2a invocation returns clean0/corrupt-complete1. #85's six-second case remains unresolved; no latency guarantee is made. #96 is separate, and P8 planning remains blocked until the full scope is delivered and writer parity reviewed.

Wire shape is `report_version=1`, capability is `coverage_revision=D2a`, and the finite promised checklist is `required_scope_revision=P7-1`. These fields do not change the package version or database schema version. Findings use fixed predicate codes and grouped occurrence counts, not distinct corrupt-track totals. Several findings can overlap on the same row; do not sum them as corrupt tracks. Completed counts are exact; interrupted counts/findings are lower bounds; blocked/unimplemented/N/A counts are unavailable, not fabricated zeroes.

## Graph ownership and counts

On v7+, current_graph checks the current pointer, current descriptors, current edges and their mirror relation. historical_graph checks all full builds (including current backing history), full-history edges and, on v8+, all positioned snapshots and edges. Established lifecycle/count/pointer/mirror/edge rules are diagnosed without changing FULL-reader tolerance, topology, eligibility, schema or package policy.

Both owners accept corruption codes `graph_lifecycle_invalid`, `graph_counts_invalid`, `graph_pointer_invalid`, `graph_mirror_invalid`, `graph_edge_invalid`. Occurrences are per invalid build for lifecycle; per invalid full-build/positioned descriptor for counts; per unequal full/positioned relation for mirror; and one OR-ed occurrence per bad edge row, even when several edge predicates fail.

Graph check counts represent semantic work, not all query deliveries: descriptors plus physical edge rows, excluding repeated preflights, mirror comparisons and lookups. The public two-build/one-edge fixture gives current/history **2/4** on v7 and **3/8** on v8–10. Empty drained graphs are completed with exact0; v6 graphs are N/A with unavailable/null counts. Every delivered SQLite row, including excluded semantic work, still charges the runtime row budget. Completion requires full streams and successful cleanup; healthy and corrupt supported graphs remain incomplete4/complete=false.

## Safety, snapshot and work limits

The adapter uses an escaped SQLite URI with `mode=ro`, `query_only`, and an explicit BEGIN/first-read snapshot. No immutable shortcut, writer adapter, DDL/DML, migration, checkpoint or ATTACH is used. The report applies only to that pinned snapshot, finite checklist and diagnostic revision—not future/restored/external bytes or general database authenticity. It does not inspect audio files or authorize repair, backfill, or mutation.

Logical read-only is **not forensic sidecar immutability**: reading a WAL database may use SHM/read locks and pin WAL history. Back up the database with a SQLite-aware procedure; do not assume copying only the main file while a writer is active captures committed WAL state. Preserve required WAL/SHM sidecars consistently. If necessary, run against a safely produced offline backup rather than an actively changing library. The command does not checkpoint, merge sidecars, or create missing databases.

Default absolute cooperative deadline is120 seconds; `--audit-deadline-seconds N` accepts only finite positive values <=120. The deadline includes access and cleanup, with a remaining-time busy timeout and progress callback. Work stops also apply at1,000,000 delivered SQLite result rows,1GiB cumulative admitted UTF8 text,32MiB runtime single-value admission, and100 grouped findings. Scalar/preflight/descriptor/relation result rows count toward the delivered-row budget. Runtime caps mean incomplete work, **not new database validity rules**. Text/BLOB admission precedes full Python value delivery; UTF16 input uses conservative safe admission and is not newly rejected as corruption. Native SQLite preparation/allocation and Python work remain cooperative: no hard wall-time/RSS bound is promised.

All paths attempt cleanup. Deadline, caps, blocked dependencies, late read errors and cleanup failures keep selected-scope completion false. Cleanup failure overrides an earlier ordinary stop, while cancellation wins with exit130; already observed findings remain visible with appropriate precision. Findings are grouped by fixed check/code keys, capped at100; attempted excess groups set `findings_truncated=true` and stop incomplete rather than silently discarding observations.

## Exits and privacy

| Exit | Meaning |
|---|---|
|2|Invalid invocation; fixed sanitized stderr, no report and no target access|
|3|Unsupported application/version or initially unreadable/refused target|
|4|LIMITED D2a report, whether healthy, corrupt-observed, blocked, capped or late-error|
|130|Cancellation/SIGINT; incomplete report after attempted cleanup|

The first compatibility read can fail even after connection open; that remains an initially unreadable target (exit3), not late read failure. Operational deadline/caps before version recognition remain incomplete4, not unsupported3. Cleanup failure can supersede an unsupported result with incomplete4.

Text and JSON output are deterministic, sanitized fixed labels/codes/counts. They do not echo paths, configuration, SQL, database-derived object names, payloads, row samples, exception text or tracebacks. Unsupported raw schema versions are not echoed. Invalid integrity options do not echo supplied tokens or values. Output remains sensitive in the ordinary sense that counts and categorical findings describe the explicitly selected database; share it deliberately.

This diagnostic does not suggest automatic repair. Keep the source and a consistent backup, preserve evidence, and investigate findings separately; successful selected work is not permission to use omitted phases as trusted inputs.
