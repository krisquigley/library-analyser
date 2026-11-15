# Explorer read policy — scoped reads (issue88 R1 + R2)

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
List and summary pages take the count and the page from one statement (a window
count over the matched candidates), so each candidate is eligibility-checked once
per request rather than once for the count and again for the page; only a cursor
past the last page runs a separate count.
No additional validation-only whole-library/history pass or validity cache is used.

Detail is keyed, including direct reads of known excluded tracks; active selection
is a separate keyed identity/audio eligibility check. Unknown/ineligible selection
is rejected. Detail retains the newest linked run even when it failed, strict
common/tags/warnings parsing and preflights all selected stage sizes before loading
payloads. Any selected-track run link whose run row is missing aborts detail,
even when another valid run is also linked. There is no new metadata size validity
cap. Responses are assembled
completely before success; a malformed consumed row aborts the response, rather
than being skipped or producing a successful partial page.

## Graph, candidate, projection and export reads (R2)

R2 extends the same scoped policy to the mood-axis graph, current full/positioned
graph edges, candidate snapshots, `track_ids` enumeration, available audio paths,
analyzer graph source projections and standalone playlist export. Active
membership applies the canonical eligibility predicate (identity, audio status and
reason) to the `tracks`/`track_audio`/`locations` base tables inside the query.
It does not trust or certify the `active_tracks`/`active_locations` view text.

What these reads consume, and therefore keep fail-closed:

- the **single current graph build** (ambiguity probe, completed status, counts,
  sparse_k/policy fields), and the status of the newest build when none is current;
- its `graph_build_edges` rows (per-row rules, `edge_count` equality) and the
  `graph_edges` mirror (exact equality); a populated `graph_edges` or
  `graph_positioned_edges` mirror with **no** current build is rejected;
- the current positioned snapshot (count) and `graph_positioned_edges` mirror;
- the **current** evidence of each selected active track (one row per identity,
  fingerprint syntax, JSON decode, full semantic/canonical payload validation),
  loaded in bounded chunks once per request;
- overrides, locations and audio rows of selected tracks.

They do **not** load or validate historical (non-current) evidence payloads,
non-current graph builds/edges/positioned snapshots, or schema topology
(`sqlite_master`, `PRAGMA table_info/index_list/foreign_key_*`). Damage there is
reported by explicit D3 (below), not by a graph or export request. Graph topology,
readiness states, automatic loading, lifecycle and the HTTP contract are unchanged.
No browser behavior, page size (default/maximum summary100), epochs, per-client
selection tokens, reset/undo or independent detail/focus/graph ownership changes
are part of this rollout. Analyzer phrase search and standalone whitespace-token
matching are intentionally not harmonized here.

Keyed selection admission is one read snapshot, not an atomic promise against a
writer committing later or against changes between HTTP requests. There is no new
writer lock, trust token, startup audit, automatic repair or migration.

## Ordinary HTTP failures

Expected compatibility, request and encountered-data failures remain HTTP **400**
with a JSON object containing **only `error`**. Fixed reader categories include
`Invalid stored metadata`, `Invalid stored stage`,
`Oversized stored stage (16 MiB limit)`, `Unexpected analysis database rows` and
`Analysis database error`; SQLite and stage exception details are not appended.
Unknown selection/detail uses `Unknown explorer track`; for detail this rule is
decided by the application use case (`find_track` returns no track), not by the
SQLite adapter. Malformed integer or JSON
request parsing uses `Invalid explorer request`. Unexpected ordinary read/selection
failures are HTTP **500**, `{"error":"Explorer request failed"}`. These failures
do not echo paths, SQL, malformed inputs or stored payloads. Existing explicit
request validation messages remain bounded and HTTP 400: candidate control policy
messages (for example `control mode must be off, soft, or hard`), malformed control
syntax (`Invalid explorer request`), projection artifact categories (for example
`resource_limit_exceeded`) and a negative `Content-Length`
(`Invalid explorer request`, without reading the body). This is not a redesign of
the separate candidate, dynamic mood-selection, projection or playlist-export
validation APIs.

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
