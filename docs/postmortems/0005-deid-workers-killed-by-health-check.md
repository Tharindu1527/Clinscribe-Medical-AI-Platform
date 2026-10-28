# Postmortem 0005: de-ID workers killed mid-request by uvicorn's health check

Type: real defect, found in passing · Date: 2026-10-28 · Severity: medium (a Scribe draft or an Ask
question fails with HTTP 500 and has to be sent again; no data lost, no PHI exposed)

## Summary

The de-ID service runs three uvicorn worker processes (since the Phase 6 load test). uvicorn's
supervisor pings every worker and kills one that does not answer within `--timeout-worker-healthcheck`,
5 s by default, as hung. Under memory pressure in the Docker VM a worker can stall for more than 5 s
while it serves a request, and it was killed with the request open: the API's de-ID client got
"Server disconnected without sending a response" and the draft failed with a bare HTTP 500. The
container stayed healthy and recorded no out-of-memory kill, because the supervisor, not the
kernel, ended the process; it started a replacement each time.

## Timeline

| when (2026-10-28, UTC) | event |
|---|---|
| 2026-10-14 | Phase 6: de-ID moved from one uvicorn process to `--workers 3` (load test: one process queued to p95 26 s) |
| 2026-10-24 | the fine-tuned tagger is adopted locally (ADR-0014): de-ID 2.1–2.3 GiB of 3.5, the whole stack ~6 GiB of the VM's 10 |
| 12:39 | a worker dies during the full test suite (`Child process [21464] died`); every test passes, nobody reads the line |
| 13:26 | two workers die while `evals/voice/asr_confidence.py --drafts 6` sends consultations: 2 of 6 drafts return 500 |
| 13:27 | investigated: `memory.events` `oom_kill 0`; uvicorn 0.54's `keep_subprocess_alive` kills a worker whose ping is not answered in time; the VM had 3.2 GB available and 1.8 GB of swap in use, the de-ID container 33,474 major page faults |
| 13:30–13:40 | reproduced, fixed and verified (below) |

## Impact

- The request a killed worker was serving fails: in the drafts run, 2 of 6 Scribe drafts. The
  Scribe listener prints the error and drafts nothing, so the consultation is sent again; Ask
  returns 500 and the doctor asks again. De-identification is stateless per call (same input, same
  surrogates), so nothing is half-written.
- Not an exposure: a failed de-ID call sends nothing onward. No PHI reached a model, log or trace.
- The load test (2026-10-14 and 2026-10-24) reported 0 errors, so the kills are rare without
  memory pressure; they became visible with the tagger's memory and a long stack uptime.

## Root cause

uvicorn treats "no answer to a ping in 5 s" as "hung" and kills the worker without waiting for its
open requests. A de-ID worker is not hung when it stalls: under memory pressure, pages of its
models are paged back in (major faults), and the thread that answers the ping cannot run meanwhile.
The 5 s default fits small web workers; it does not fit a worker that holds 0.7 GB of models in a
VM using swap.

Reproduction, no model calls: 396 PriMock57 turns sent one at a time to `/deidentify`: 1 dropped
connection and 1 worker death; median call 98 ms, the slowest 5.37 s (the kill). The dropped call was
a 4-character turn that takes 62–257 ms when sent alone nine times, so it is not the input.

## Fix

`docker-compose.yml`: the de-ID service runs with `--timeout-worker-healthcheck 60`. A worker that
really hangs is still replaced, after a minute instead of five seconds.

Verified on the running service, by freezing one worker with SIGSTOP for 8 s: with the 5 s default
the supervisor killed it ("Child process [10] died"); with 60 s it resumed and kept serving. The
same 198 turns replayed three times after the fix: 594 calls, 0 errors, 0 deaths (slowest 3.9 s, so
that replay did not stall past 5 s; the SIGSTOP test is the evidence). The drafts run afterwards
produced every draft with no worker death (`evals/reports/voice/asr_confidence.md`).

## Detection gaps

- Worker deaths are logged at INFO by uvicorn and counted nowhere; the container healthcheck and
  `docker stats` look normal.
- The API turns a de-ID connection failure into a bare 500; only model-gateway failures get a
  message (`_run`), so the failure looked like an application bug.

## Prevention

- `tests/unit/test_compose_workers.py`: every Compose service that runs several uvicorn workers
  sets `--timeout-worker-healthcheck` to at least 30 s.
- Not done: a retry in the de-ID client on a dropped connection (safe, since de-ID is idempotent),
  and a 502 with a message for de-ID failures in the API. With the fix the known cause is gone;
  either is a small follow-up if drops are seen again.
