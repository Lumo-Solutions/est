# BOQ-led estimation agent: report

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

## Phase 6: two index children (measured 10 Oct, Docker VM 29 GB)

150-file scale pack (707 MB) into project P6-IDX-A, mock provider, AI classify on for the run, then Measure all on the 66 drawings it produced, `INDEX_CONCURRENCY=2` (index worker `--max-memory-per-child` 700 MB, 1.5 CPUs).

| | result |
|---|---|
| wall clock, 66 drawings | **28 min** (64 ready, 2 failed: one 300 s time-out on a long set, one flush error from the same time-out) |
| `index_sheets` job time | avg 39.8 s, median 16.2 s, max 178 s; 64 jobs = 42 min of job time, so one child needs at least 42 min (about 1.5x faster with two; the container is capped at 1.5 CPUs) |
| other stages (avg) | embed 2.2 s, geometry 2.2 s, title block 0.7 s |
| peak memory (docker stats, 5 s samples) | index worker **1,344 MiB** of 2 GiB; ingest worker 1,310 MiB; backend 870; Postgres 2,583; SeaweedFS 869; Keycloak 818; all containers together about 8.7 GiB of the 29 GB VM |

Enabled as the dev default in `deploy/docker-compose.override.dev.yml` (`INDEX_CONCURRENCY` in `deploy/.env` still wins; base file and prod stay at 1). The agent worker stays at concurrency 1: the plan fixes one section at a time. Opt-in 2,000-file page test (`SCALE_PROJECT=SCALE-SIM-2`): passed.

## Verification

Backend: unit 756 passed; integration 375 passed and 1 failed on the full run (the hyphenated-number search bug, fixed in 170e070; test_file_manifest and test_boq_agent re-run after the fix: 34 passed; the full suite was not re-run); API suite passed; vitest passed. Each run alone, not alongside Playwright.

Real-backend Playwright, each spec alone with `--workers=1` (stack: real Keycloak, workers, S3, mock AI provider):

| spec | result | note |
|---|---|---|
| admin-audit-permissions | passed (8) | |
| ai-first-intake | passed (4) | |
| ai-walkthrough | passed (2) | annotation poll raced; fixed. Once hung in the full run (unexplained, not reproduced) |
| approvals-inbox | **failed (1 of 3)** | tile shows the first 5 pending, oldest first; 18 stale pending cost_rate_change requests hide the new one. Environment state, not an app regression; not changed |
| boq-agent | passed (1), re-run at the end | |
| costlib-module-e | passed (3) | one 5 s-timeout flake on the first run, passed alone |
| dwg-conversion | passed (3) | spec rewritten: the Drawings picker no longer exists |
| home-dashboard | passed (3) | |
| intake-scale | passed (2) + opt-in 2,000-file page test passed | |
| layout-widths | passed (1) | |
| login / logout | passed (2 / 2) | |
| member-removal | passed (1) | spec: members are in the Edit project drawer |
| modal-replacements | passed (2) | |
| pdf-takeoff-viewer | passed (1) | |
| phase4-accessibility | passed (18) | |
| platform-admin | passed (1) | |
| procurement | passed (7) | |
| project-members-scenarios | passed (3) | spec: location and members are in the Edit project drawer |
| project-pages | passed (9) | |
| quarantine-quotes-bidleveling | passed (6) | |
| quotation-settlement-overrides | passed (4) | |
| settlement / settlement-winloss-roles | passed (9 / 4) | |
| step-up-freshness | skipped | own config, lowers Keycloak step-up windows; not part of the normal run |
| taxonomy-tree | passed (2) | |
| tender-intake | passed (4) | first run failed only on the SeaweedFS host port after the Docker restart |
| typology-boq-procurement | passed (6) | |
| vendors-prequal | passed (4) | spec: open the new vendor by its id (list shows 50) |

One uninterrupted full run, `--workers=1`: **98 passed, 2 failed (ai-walkthrough hang, approvals-inbox), 1 skipped (opt-in scale test), 1 did not run (second ai-walkthrough test, after the hang), 29.3 min.**
Assertion changes: none loosened. Specs that depended on per-file AI at upload now turn the tenant setting on for their file (`useAiClassify`); dwg-conversion drops the assertions about the removed picker's hint text and the project-list link.

