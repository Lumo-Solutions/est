# BOQ agent log (resume here)

Branch: `feat/boq-agent` (from master a7f3825). Brief: `docs/boq-agent-brief.md`. Plan: `docs/boq-agent/plan.md`.

## Status
- [x] Plan written
- [x] Phase 1 code: 0040 manifest, fast PDFium read, AI-free process_one, rules-only routing of BOQ/addenda, FTS+vector search, backfill CLI (needs --project or --all). Unit 755 pass; intake integration suites 70 pass. Micro-benchmark on 292 files of the scale pack: median 0.30 s/file (read 0.001, extract 0.10, embed 0.10). full-stack 1,600-file numbers are in report.md (Phase 1)
- [x] Phase 2 backend: done and tested (integration 26 agent tests + all suites green in groups, API 5 agent tests). Was: written (0041/0042, app/agent/*, services/agent.py, routes, tasks, worker container, submit gate, mock policy); unit tests pass; TODO integration tests (tests/integration/test_boq_agent.py), api tests, dev-stack run
- [~] Phase 3 UI: two subagents launched (agent/agent-tab-ui, agent/agent-lines-ui), prompts in scratchpad; main session must verify commits/diffs/allow-lists before merging
- [~] Phase 4 eval: agent-eval (mock) and agent-smoke (real, $0.08-0.09) run on AI-DEMO-E2E-MUOQDBNZ; TODO Alibaba bill check (user), final numbers in report
- [ ] Phase 5 real pack (user present only)
- [x] Phase 6: continuation priority + time-out message done; 2 index children now the dev default (measured, see report.md); specs no longer rewrite tracked screenshots; agent worker stays at concurrency 1 (the plan says 1)
- [ ] report, merge

## Entries
- 2026-10-10: read the brief, gateway, intake models/worker/processing, settlement + pricing_ai services; wrote the plan.
  Not touching packs 948b4c0f / 661d42e3.
- 2026-10-10 (later): Phase 1 merged into the branch history (d4eed8a, 634e985). Dev DB migrated to 0040 (docker exec installtec_backend alembic upgrade head); packs 948b4c0f / 661d42e3 are paused and untouched (562 `received` files stay received). Backfill must be run with --project, never --all, on this dev DB until the user agrees.
- 2026-10-10 (later): Phase 2 core written. Deviations from the brief: read_title_block uses the manifest (no model call); markup advice not wired into the run summary yet (open item); added a 6th table agent_run_sections (per-section state) and agent_runs.kind for chat turns.
- Stopped containers to free RAM (vllm, dwg, greenmail, mailpit, vlm/email/quotation/convert/agent/index workers); restart with docker compose up -d before dev-stack work. Test stack was torn down.

- 2026-10-10 (resume): Docker VM total 30082 MB, 26.9 GB available, 8 GB swap (.wslconfig applied). Full dev stack restarted with docker start (mock AI env override still on backend/workers). Specs run one at a time, --workers=1.
- 2026-10-10 (resume, later): all real-backend specs run one at a time with `--workers=1`, then one uninterrupted full run (98 passed, 2 failed, 1 skipped, 1 did not run, 29.3 min). Table in report.md. Fixes: useAiClassify specs committed; ai-walkthrough annotation poll raced (waited only for the first sheet); member-removal, project-members-scenarios (members and location moved into the Edit project drawer), vendors-prequal (new vendor off page 1), dwg-conversion (Drawings picker is gone: upload via the drawing endpoint + ingest) were stale specs; real app bug found by an integration test and fixed: file search did not match hyphenated numbers like C-101 (170e070). One host quirk: after the Docker restart the SeaweedFS port 8333 gave empty replies from the host until the container was restarted.
- Workers that came back with `docker start` kept their old env (real provider): workers that kept the real provider made Qwen calls (ai_calls since 11:30 UTC with provider openai_compatible: 11 billed rows, 8 error rows, 49 cache hits; total about $0.019). Recreated with the shell-only AI_PROVIDER=mock override.
- 2026-10-10 (end): dev workers recreated WITHOUT the mock override; `make check-ai-env` OK; backend and all workers report AI_PROVIDER=openai_compatible, DEV_DISABLE_MFA=true (MFA off). Tenant ai_classify setting is back off. Test stack down. Projects P6-IDX-A/B (150-file pack, Phase 6 measurement) remain on the dev DB; packs 948b4c0f / 661d42e3 untouched.
- (Resolved by fix/approvals-tile below: approvals-inbox, stale requests, ai-walkthrough timeout.) step-up-freshness is not part of the normal run (own config, reconfigures Keycloak).
- 2026-10-10 (fix/approvals-tile): tile shows the newest 5 + total + View all N; withdraw endpoint and /approvals/mine; dev-withdraw-stale-approvals (44 withdrawn after a dry run) and dev-delete-demo-project (P6-IDX-A/B deleted); useApprovalCleanup in 7 specs; approvals-inbox rewritten to count and use /approvals; ai-walkthrough 6 min/30 s timeouts, 5 of 5 back-to-back runs with ai-first-intake passed; .claude/ ignored. Suites each alone: unit 763, API 122, vitest 371, integration 377 (third run; the first two had asyncpg connect timeouts on two different tests each, unexplained). Dev workers recreated without the mock override again (the specs need the mock; I used the shell-only AI_PROVIDER=mock for the Playwright and loop runs), `make check-ai-env` OK, MFA off, test stack down, 0 pending approvals.

