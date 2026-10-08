# Public synthetic graph-read integrity harness

Run from a repository checkout with Python 3.11+:

```sh
python3 -m tools.graph_read_benchmark --synthetic-smoke
```

The command prints a JSON report to stdout. It composes a public synthetic graph
DTO through the existing indexed v3 mapper and checks a fake HTTP response. It
uses no private library, live server, audio, network, database or resource cap.
The report labels its scope `public-synthetic-smoke` and `synthetic_only: true`;
`measurement.attempted` and `measurement.succeeded` are both 1 on success. This
is an integrity/usability smoke, **not a graph-read latency benchmark**.

## Reusable measurement boundary

`tools.graph_read_benchmark.measure_samples(probes, expected=...,
db_fingerprint=...)` accepts one callable per attempted public response exchange.
Each response exposes `status`, `getheader('Content-Length')`, and `read()`.
Provide an independently established SHA256 of the full expected UTF-8 response
bytes and expected `nodes`, `links`, and `unpositioned` counts. Do not derive the
oracle from the response being checked. Supply a database fingerprint callback
that observes the same prepared synthetic database before and after an attempt.

The report retains attempts in order, including HTTP errors, timeout and memory
failures. A successful sample requires HTTP 200, exact Content-Length, a valid
indexed-v3 response, expected full-body hash and counts, and unchanged database
fingerprint. The v3 checks are response-integrity checks, not a replacement for
the readers' full graph-feature evidence semantic validation. A caller remains
responsible for probe timeout/resource enforcement and lifecycle cleanup.

`nearest_rank(values, percentile)` uses the sorted sample at rank
`ceil(percentile * sample_count / 100)`, not interpolation. For 20 observations,
p95 is rank 19. This arithmetic does not make small samples statistically robust;
always report sample count and method, and retain failures separately.

`summarize_work(raw_rows=..., validations=...)` reports supplied observed counters
keyed by `(track_id, run_id)`, plus totals. It does not instrument a reader or
infer work from SQL text. The contract tests count actual yielded rows and wrap
the real semantic validator in **both** readers, excluding constructor work.
The pre-PR-B baseline performed `2N + H` raw-row deliveries and complete
validations per request (N selected current identities, H other evidence
identities). The bounded warm reader now performs `N + H`: every evidence row
is fully semantically and canonically validated once per request, including
historical rows. Selected current rows are immediately mapped into the
application-owned incremental projection, rather than retained as decoded
payload dictionaries or complete records. Repeated requests validate again;
there is no cross-request validation cache. This structural work reduction is
not a wall-clock latency or real-library memory-cap claim.

## Focused checks

```sh
python3 -m unittest discover -s tests/unit -p 'test_graph_read_benchmark*.py' -v
python3 -m unittest -v tests.unit.benchmark_tools.test_graph_read_benchmark tests.unit.benchmark_tools.test_graph_read_benchmark_cli
python3 -m unittest discover -s tests/architecture -v
python3 -m unittest -v \
  tests.integration.infrastructure.test_graph_feature_evidence_payload_streaming.GraphFeatureEvidencePayloadStreamingTests.test_payload_chunk_query_does_not_request_sql_ordering_in_analyzer_and_standalone_mirrors \
  tests.integration.infrastructure.test_compact_mood_axis_graph_red.CompactMoodAxisGraphReadTests.test_standalone_evidence_payload_chunks_stream_rows_without_materializing_raw_payloads
```

This bounded delivery does **not** provide full-header/transfer timing, process
warm/cache labeling, N=8/32/451 profile generation, 5k/20k throughput, browser
render evidence, or OOM/resource-cap acceptance. The smoke itself measures no
production reader optimization. PR B changes no
schema or validation trust policy and does not establish that Issue #44's
latency goals are met. Warm graph requests retain the existing raw-row size cap,
graph integrity checks and legacy fallback, and must finish validating all
current and historical evidence before returning success. Final graph output
still grows with the library; bounded per-row intermediates are not a universal
1GiB guarantee for arbitrary graphs or concurrent requests. Existing legacy
raw-stage fallback retains its pre-existing stage loading behavior; the bounded
intermediate guarantee here concerns compact evidence rows. Future
timing/resource runs need separate explicit scope and synthetic fixtures;
container operations must use Podman, never Docker.
