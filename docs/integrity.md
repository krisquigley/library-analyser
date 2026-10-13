# LIMITED offline integrity diagnostic (D1)

```sh
music-analyzer integrity --database DB --json
music-analyzer --database DB integrity
python -m music_analyzer integrity --database DB --audit-deadline-seconds 30
```

A database path must be supplied explicitly. Repeated root/subcommand `--database` options (including `--database=DB`) select the **last explicit value in argv order**; earlier values are never opened. The command does not load Settings, default/XDG configuration, models, inference backends, FFmpeg, audio files, cache, graph builders or servers. Configuration/model and unrelated command options are rejected. It performs no migration or repair and does not change SQLite `user_version`.

## What D1 covers — and does not certify

D1 recognizes the existing application ID and true schema versions **6–10**, checks the exact existing FULL-reader schema contract (including its existing legacy tolerances), and examines every core track identity/digest/size and audio-policy row, including missing/orphan audio relationships. Both FULL readers and their trust behavior remain unchanged.

Every report exposes the finite twelve-check checklist: compatibility, schema, core_rows, metadata, retained_stages, current_graph, historical_graph, current_evidence, historical_evidence, sqlite_physical, sqlite_foreign_keys, resource_access. Metadata, retained stage payloads, graph/evidence semantics and SQLite physical/foreign-key checks are **not implemented in D1**. Graph checks are genuinely not applicable in v6, and evidence checks in v6–8, only after trustworthy application/version recognition. Missing applicable coverage is never labeled not applicable. Schema drift can block dependent core checks.

Even a healthy v6 database returns `status=incomplete`, `complete=false`, `stop_reason=scope_not_implemented`, **exit4**. Core corruption findings remain visible but do not change that incomplete precedence. `implemented_scope_complete=true` means only the selected schema/core work and resource cleanup completed; it can also be true when fully drained core scans found corruption. It is **not** P7 completion, a clean result, a trust token, or suitability for P8. No D1 invocation returns clean0/corrupt-complete1. #85's six-second case remains unresolved; no latency guarantee is made. #96 is separate, and P8 planning remains blocked until the full scope is delivered and writer parity reviewed.

Wire shape is `report_version=1`, capability is `coverage_revision=D1`, and the finite promised checklist is `required_scope_revision=P7-1`. These fields do not change the package version or database schema version. Findings use fixed predicate codes and grouped occurrence counts, not distinct corrupt-track totals. Several findings can overlap on the same row; do not sum them as corrupt tracks. Completed counts are exact; interrupted counts/findings are lower bounds; blocked/unimplemented/N/A counts are unavailable, not fabricated zeroes.

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
|4|LIMITED D1 report, whether healthy, corrupt-observed, blocked, capped or late-error|
|130|Cancellation/SIGINT; incomplete report after attempted cleanup|

The first compatibility read can fail even after connection open; that remains an initially unreadable target (exit3), not late read failure. Operational deadline/caps before version recognition remain incomplete4, not unsupported3. Cleanup failure can supersede an unsupported result with incomplete4.

Text and JSON output are deterministic, sanitized fixed labels/codes/counts. They do not echo paths, configuration, SQL, database-derived object names, payloads, row samples, exception text or tracebacks. Unsupported raw schema versions are not echoed. Invalid integrity options do not echo supplied tokens or values. Output remains sensitive in the ordinary sense that counts and categorical findings describe the explicitly selected database; share it deliberately.

This diagnostic does not suggest automatic repair. Keep the source and a consistent backup, preserve evidence, and investigate findings separately; successful selected work is not permission to use omitted phases as trusted inputs.
