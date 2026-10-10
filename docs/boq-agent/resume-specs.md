# Resume: real-backend specs after the memory kill (10 Oct 2026)

The previous Claude Code session was closed after the host killed the sequential Playwright run for low memory. The user has freed RAM. Pick up from here. `docs/boq-agent-brief.md`, `docs/boq-agent/log.md` and `docs/finish-brief.md` section A still apply. Main session only, no subagents for this.

## State you are inheriting
- Branch `feat/boq-agent`, HEAD 6b24fc6. **Uncommitted** (they typecheck but have never been run):
  - `frontend/e2e/real-backend/helpers.ts`: the new `useAiClassify` helper (switches the tenant `ai_classify` setting on and restores it afterwards);
  - `tender-intake.spec.ts`, `ai-first-intake.spec.ts`, `ai-walkthrough.spec.ts`: use it; `ai-first-intake` also writes screenshots to `test-results/` unless `UPDATE_QA_SCREENSHOTS=1`.
- The dev stack's backend, ingest, index and agent workers were recreated with a **mock AI provider env override** (not by editing `deploy/.env`). Check with `docker inspect` which env they have now before running anything.
- Stopped from the memory cleanup: vllm, dwg converter, greenmail, mailpit, vlm/email/quotation/convert workers. Test stack is down.
- Already passing: `boq-agent`, `intake-scale` (2 passed, 1 skipped opt-in).
- **The user upgraded the machine from 16 GB to 48 GB of RAM** and the Docker VM now has 29 GB total and 8 GB swap (.wslconfig memory=30GB, applied 10 Oct). The earlier 7.7 GiB VM figure is out of date. Do not change `.wslconfig` yourself.

## Steps
1. **Memory check first:** `docker run --rm alpine free -m`. Record the VM total in the log.
   - If the total is **20 GB or more** (the user measured 29 GB total, 27 GB available on 10 Oct): bring the full dev stack back up (`docker compose ... up -d`, all the containers stopped in the cleanup). Specs still run one at a time with `--workers=1` (they share one dev DB), but there is no need to stop and start containers between specs.
   - If the total is under 20 GB (for example still about 8 GB): the `.wslconfig` has not taken effect. Tell the user and stop; do not run specs on 8 GB again.
2. Never run the MCP browser at the same time as a spec.
3. Run, **one spec at a time, `--workers=1`**, memory check between each:
   1. `tender-intake`
   2. `ai-first-intake`
   3. `ai-walkthrough`

   If a spec fails, find the cause, fix it (spec or app), re-run that spec alone, then continue. Do not loosen an assertion just to make it pass; if the old assertion depended on per-file AI at upload, say so in the commit message.
4. When those three pass, commit the spec changes (conventional commit, one per logical change).
5. Run every other real-backend spec the same way, one at a time (the dwg converter is needed for `dwg-conversion`; mail and the email/quotation workers for `procurement` and `quarantine-quotes-bidleveling`). Re-run `boq-agent` once at the end. Then, as a bonus now memory allows, try **one uninterrupted full real-backend run** (`--workers=1`): the handoff lists "no full real-backend run since the AI work" as an open item.
6. If the host kills a run again: stop, write in `docs/boq-agent/log.md` which spec was running and what had already passed, and tell the user. Do not restart on your own.
7. Run the backend unit, integration and API suites and vitest, each on its own (not alongside Playwright). With the extra memory, also re-check that the opt-in 2,000-file intake-scale test can run, and record the Phase 1 full-stack 1,600-file numbers still marked TODO in the log.
7b. **Phase 6 item now possible:** enable 2 index children on dev (it was skipped because the VM had 7.7 GiB), and the agent worker can go above concurrency 1 if the plan allowed it. Measure memory with both, record in the report.
8. Put the dev workers back on the user's Qwen config: recreate them **without** the mock override (`docker compose ... up -d --force-recreate <services>`), then `make check-ai-env`. Do not edit `deploy/.env`. MFA stays off.
9. Update `docs/boq-agent/log.md` and `docs/boq-agent/report.md` with a table of every real-backend spec: passed / failed / skipped, and any fixes. Then finish the remaining items from the log (report, merge `--no-ff` to master). Nothing is pushed.

Packs 948b4c0f (project 102) and 661d42e3 (project 103) stay paused and untouched.
