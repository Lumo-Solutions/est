# BOQ-led estimation agent: report (in progress)

Brief `docs/boq-agent-brief.md`, plan `docs/boq-agent/plan.md`, resume log `docs/boq-agent/log.md`.

## Phase 1: fast index (numbers)

Dev stack (Docker VM 7.7 GiB, ingest worker 2 children), project BOQSCALE (synthetic scale pack, 1,600 files, 2.3 GB: 560 vector PDFs A4-A0, long sets, scans, large PDFs, DXF, BOQ workbooks, specs, duplicates, junk, zips), real Keycloak login, resumable upload client, **no AI calls** (tenant `intake_ai_classify` off, Alibaba provider configured).

| | before (per-file AI, `docs/intake-scale/report.md` §6, mock provider) | after |
|---|---|---|
| intake reading rate | about 40-60 files/min (2,051 files, about 40 min once uploaded; with a real model each file is also one API call) | **111 files/min** processing only (1,064 files in 574 s) |
| time per file task (median / p95) | seconds (model call) | **0.24 s / 0.79 s** (download 0.11, extract 0.01, persist 0.05, accept 0.05; embedding moved off the critical path) |
| 1,600 files end to end | hours with a real model | **about 14.4 min** processing-only at 111/min; 16.8 min measured first run with the upload still running and two worker restarts |
| AI calls / cost at upload | one per file | **0 / 0 USD** |

First measured run (upload concurrent with reading): median 0.90 s per file (persist 0.31 s and inline embedding 0.14 s under CPU contention). Two changes got it to 0.24 s: the embedding is filled in afterwards in batches of 16 by the intake tick (search is by text until then), and the per-file timing log (`tender_intake: file ... done in`) shows where the rest goes. 1,626 files indexed, 0 partial, 1,531 embedded when the last timing was taken.

Bugs found by this run and fixed: the dispatcher still waited for a cost confirmation when an external provider was configured although upload no longer calls a model; an embedding batch of 500 killed an ingest child (SIGKILL) and stalled the queue.

Micro-benchmark (292 files, no S3/DB): median 0.30 s per file including embedding.
