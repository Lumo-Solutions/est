# BOQ agent log (resume here)

Branch: `feat/boq-agent` (from master a7f3825). Brief: `docs/boq-agent-brief.md`. Plan: `docs/boq-agent/plan.md`.

## Status
- [x] Plan written
- [x] Phase 1 code: 0040 manifest, fast PDFium read, AI-free process_one, rules-only routing of BOQ/addenda, FTS+vector search, backfill CLI (needs --project or --all). Unit 755 pass; intake integration suites 70 pass. Micro-benchmark on 292 files of the scale pack: median 0.30 s/file (read 0.001, extract 0.10, embed 0.10). TODO: full-stack 1,600-file run + before/after in report.md
- [x] Phase 2 backend: done and tested (integration 26 agent tests + all suites green in groups, API 5 agent tests). Was: written (0041/0042, app/agent/*, services/agent.py, routes, tasks, worker container, submit gate, mock policy); unit tests pass; TODO integration tests (tests/integration/test_boq_agent.py), api tests, dev-stack run
- [~] Phase 3 UI: two subagents launched (agent/agent-tab-ui, agent/agent-lines-ui), prompts in scratchpad; main session must verify commits/diffs/allow-lists before merging
- [~] Phase 4 eval: agent-eval (mock) and agent-smoke (real, $0.08-0.09) run on AI-DEMO-E2E-MUOQDBNZ; TODO Alibaba bill check (user), final numbers in report
- [ ] Phase 5 real pack (user present only)
- [~] Phase 6: continuation priority + time-out message done; 2 index children NOT enabled (VM 7.7 GiB); TODO specs stop rewriting tracked screenshots
- [ ] report, merge

## Entries
- 2026-10-10: read the brief, gateway, intake models/worker/processing, settlement + pricing_ai services; wrote the plan.
  Not touching packs 948b4c0f / 661d42e3.
- 2026-10-10 (later): Phase 1 merged into the branch history (d4eed8a, 634e985). Dev DB migrated to 0040 (docker exec installtec_backend alembic upgrade head); packs 948b4c0f / 661d42e3 are paused and untouched (562 `received` files stay received). Backfill must be run with --project, never --all, on this dev DB until the user agrees.
- 2026-10-10 (later): Phase 2 core written. Deviations from the brief: read_title_block uses the manifest (no model call); markup advice not wired into the run summary yet (open item); added a 6th table agent_run_sections (per-section state) and agent_runs.kind for chat turns.
- Stopped containers to free RAM (vllm, dwg, greenmail, mailpit, vlm/email/quotation/convert/agent/index workers); restart with docker compose up -d before dev-stack work. Test stack was torn down.
