# Load test: Ask endpoint (Phase 6)

Current configuration: **de-ID with 3 workers** (table below). Before/after and the bottleneck
analysis follow the table.

3 questions per session, sent one after another; sessions run concurrently.
The model is the gateway's canned `clinscribe-mock` alias (no provider call), so the
numbers measure ClinScribe itself: auth, de-ID, the agent graph, guidelines-mcp retrieval
(CPU), druggraph-mcp, the gateway and the audit log, on one laptop (12 logical CPUs,
WSL2 10 GB). Latency is per request, client side, successful requests only.

| sessions | requests | errors | p50 ms | p95 ms | max ms | throughput req/s |
|---|---|---|---|---|---|---|
| 10 | 30 | 0 | 1712 | 2863 | 2966 | 5.12 |
| 50 | 150 | 0 | 8119 | 10048 | 11971 | 5.38 |
| 100 | 300 | 0 | 14541 | 25110 | 25231 | 5.25 |

## Before and after: de-ID workers (2026-10-14)

| sessions | 1 worker: p50 / p95 ms | 3 workers: p50 / p95 ms | throughput req/s (1 → 3 workers) |
|---|---|---|---|
| 10 | 2,553 / 13,875 | 1,712 / 2,863 | 1.68 → 5.12 |
| 50 | 10,766 / 62,794 | 8,119 / 10,048 | 1.80 → 5.38 |
| 100 | 22,046 / 65,304 | 14,541 / 25,110 | 3.09 → 5.25 |

No request failed in either run (0 / 480 each).

**How the bottleneck was found:** span durations from the local trace export during the first run
(`mcp <tool>` spans added to the agent's tool client for this purpose):

| span | calls | p50 ms | p95 ms |
|---|---|---|---|
| POST /deidentify | 1,990 | 39 | 26,297 |
| mcp search_guidelines | 486 | 7,610 | 23,032 |
| chat clinscribe-mock (gateway + mock model) | 702 | 37 | 78 |

The de-ID service is called twice per question (by the API, and again inside guidelines-mcp before
the encoders) and ran in one process: fast alone (p50 39 ms), but requests queued behind each other
and behind the CPU-bound encoders on the same 12 logical CPUs. Three uvicorn workers (+0.8 GB) cut
p95 at 10 sessions from 13.9 s to 2.9 s and tripled throughput.

**What limits it now:** guidelines-mcp (dense encoder + BM25 + ColBERT on CPU, one process) caps
throughput near 5 requests/s. Next steps, by expected gain: run the encoders on the GPU (or the int8
ONNX export), batch concurrent queries, run 2 guidelines-mcp replicas, and skip the second de-ID call
when the caller already holds de-identified text from a trusted service (keeping it for external
callers). The model provider is not in these numbers: real free-tier calls add 1-4 s per answer
(`evals/reports/llmops/failover_latency.md`).
