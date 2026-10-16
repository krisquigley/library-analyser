# Explorer read policy — R1 partial rollout

Ordinary reads in both the analyzer and standalone Explorer now use scoped
validation: metadata, paginated lists/summaries, keyed detail and active-selection
admission. Each repository operation opens a pinned read-only transaction against
the chosen existing database (`mode=ro`, `query_only`); committed WAL frames remain
visible. The compatibility guard checks only `application_id` and supported
`user_version` **6–10** in that same snapshot. It does not enumerate schema
columns/indexes/constraints or run an integrity audit.

This is an intentional writer-first trust policy, not authentication of a file.
Supported writer mutations own their finite invariants before commit/publication.
Ordinary readers validate the identities, audio eligibility, locations and metadata
they actually consume. Search/sort/count can consume nonmatching or unreturned
candidates; required SQL/UDF validation still applies there. Count and sorting may
scan the catalogue: neither the whole search nor each request is promised O(1).
No additional validation-only whole-library/history pass or validity cache is used.

Detail is keyed, including direct reads of known excluded tracks; active selection
is a separate keyed identity/audio eligibility check. Unknown/ineligible selection
is rejected. Detail retains the newest linked run even when it failed, strict
common/tags/warnings parsing and preflights all selected stage sizes before loading
payloads. There is no new metadata size validity cap. Responses are assembled
completely before success; a malformed consumed row aborts the response, rather
than being skipped or producing a successful partial page.

## What remains FULL

**R1 does not complete issue88.** Graph/candidate/projection, genuine `track_ids`
enumeration and standalone playlist-export paths retain their previous FULL
validation temporarily for R2. Graph topology, readiness, current evidence,
automatic loading and lifecycle are unchanged. Analyzer source projections and
standalone export keep their existing capabilities. No browser behavior, page size
(default/maximum summary100), epochs, per-client selection tokens, reset/undo or
independent detail/focus/graph ownership changes are part of this rollout.
Analyzer phrase search and standalone whitespace-token matching are intentionally
not harmonized here.

Keyed selection admission is one read snapshot, not an atomic promise against a
writer committing later or against changes between HTTP requests. There is no new
writer lock, trust token, startup audit, automatic repair or migration.

## Ordinary HTTP failures

Expected compatibility, request and encountered-data failures remain HTTP **400**
with a JSON object containing **only `error`**. Fixed reader categories include
`Invalid stored metadata`, `Invalid stored stage`,
`Oversized stored stage (16 MiB limit)`, `Unexpected analysis database rows` and
`Analysis database error`; SQLite and stage exception details are not appended.
Unknown selection/detail uses `Unknown explorer track`. Malformed integer or JSON
request parsing uses `Invalid explorer request`. Unexpected ordinary read/selection
failures are HTTP **500**, `{"error":"Explorer request failed"}`. These failures
do not echo paths, SQL, malformed inputs or stored payloads. Existing explicit
request validation messages remain bounded. This is not a redesign of the separate
dynamic mood-selection or playlist-export validation APIs.

## Old, external or restored databases and D3

Application/version recognition does not certify schema topology, completeness,
source authenticity or future bytes. An old/external/restored file can pass the
cheap guard while containing omitted rows, arbitrary schema drift, unrelated
corruption or invalid retained history. Scoped validation intentionally cannot
detect all such problems. A missing required table/column or operational read
failure is reported safely, not converted into an empty catalogue or a corruption
certificate.

For an explicit full audit, use D3 on an owner-selected safe offline/consistent
snapshot (example only; no default/private path is selected):

```sh
music-analyzer integrity --database "$PUBLIC_OFFLINE_DB" --json --audit-deadline-seconds 30
```

D3 remains unchanged: full schema/core/metadata/retained-stage/current and
historical graph/evidence/physical/FK coverage. Exit **0** means complete clean,
**1** complete corrupt, **2** invalid invocation, **3** unsupported or initially
unreadable, **4** incomplete/resource/read/cleanup stop, **130** cancellation.
Incomplete is not clean or confirmed corruption. A clean report is not a request
trust token or repair authorization, and is not a hidden prerequisite for search.
D3 does not repair or migrate. Manual repair/rescan/reanalysis remains a separately
approved writer action.

Use a SQLite-aware consistent backup; never copy the main file alone while a
writer is active. Read-only WAL access can take coordination locks and pin frames;
it is not forensic `immutable=1` access or a guarantee of immutable sidecars.
See [the complete D3 contract](integrity.md) for limitations and report semantics.
