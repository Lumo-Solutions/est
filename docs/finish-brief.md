# Est Build: Finish Brief (after docs/v2.md)

Read `docs/v2.md` and `docs/ui-qa/log.md` first. Keep `docs/ui-qa/log.md` current, and when resuming, read it and continue from the first unfinished step.

## A. Subagent control (mandatory, following the v2 process incidents)
In the last run, one subagent merged a phase and started the next on its own, another restyled pages it wasn't assigned, and another reported invented commit hashes. These rules prevent a repeat:

1. **Only the main session** runs `git merge`, `git checkout`/`switch`, `rebase`, `reset`, `stash`, `cherry-pick` and branch creation or deletion, and it's the only one that commits to `master`. **Nobody pushes.**
2. **Every subagent runs with `isolation: "worktree"`** on its own branch named `agent/<task>`, never in the main working directory.
3. **Every subagent prompt includes:**
   - one task;
   - an explicit **file allow-list** (it may edit only those files);
   - what "done" means;
   - the forbidden list: any git command except `add`, `commit`, `status`, `diff` and `log` in its own worktree; `docker compose` up, down or restart; `bootstrap.sh` and `make dev-*`; `deploy/.env`; spawning further agents; and continuing past its task.
4. **Subagents never touch the shared dev stack.** They may run only `tsc`, `oxlint`, `vitest` and backend unit tests in their worktree. **Every** stack-dependent run (Playwright real-backend, integration, api, `dev-simulate`) is done by the main session, one at a time, with `--workers=1`.
5. **Security-sensitive files are main-session only:** anything under `backend/app/security`, `core/config.py`, auth routes, `approvals.py`, `deploy/keycloak`, migrations, RLS policies and `docker-compose*`.
6. **At most 2 subagents at a time**, and none while a stack-dependent test is running. **Never resume** a finished subagent to "continue"; start a fresh one with a new, narrow prompt.
7. **The main session verifies before it accepts anything.** For each agent branch: check that the commits really exist (`git log agent/<task>`), read the full diff, confirm that only allow-listed files changed, and re-run the relevant checks yourself. A report with no matching tool output, or with commits that don't exist, is rejected, and the task is redone in a fresh agent. Merge into the phase branch only after this, and record the verification in the log.
8. **Models:** Opus for the main session, reviews and anything security-related. Sonnet for scoped UI or test work. Haiku or Explore for read-only searches.

## B. Steps

### 1. Save the dev MFA switch (main session)
The `DEV_DISABLE_MFA` implementation from another session is **uncommitted** in the working tree on `phase-4-design-system`. Don't lose it and don't mix it into Phase 4:
- From the current HEAD, `git switch -c feat/dev-mfa-switch` (this carries the working changes over), then commit them in logical commits: backend switch and tests; keycloak/bootstrap and `dev-set-mfa.sh` with the make targets; frontend banner; e2e and docs updates.
- **Don't** commit `.claude/`, `.playwright-mcp/` or `docs/v2.md` in these commits. Add `.playwright-mcp/` to `.gitignore`, and commit `docs/v2.md` separately as docs.
- Run backend unit tests and vitest. Then, with the stack: `make dev-mfa-off` and `login.spec.ts`; `make dev-mfa-on` with `settlement.spec.ts` and `step-up-freshness.spec.ts`; then `make dev-mfa-off` again. Leave the stack with MFA **off**, because the user will test that way.
- Merge order: `phase-4-design-system` into `master` first (step 2), then `feat/dev-mfa-switch` into `master`.

### 2. Close and merge Phase 4
- `git switch phase-4-design-system`. Run these one at a time with `--workers=1`, with MFA **on**: `step-up-freshness.spec.ts`, `quotation-settlement-overrides.spec.ts`, `modal-replacements.spec.ts` and `phase4-accessibility.spec.ts` (including the SettlementPage check).
- Fix `BoqReconciliationPage`'s bare `text-success` and add its axe check.
- Check layouts at 1440, 1280 and 1024 wide on every page. Screenshots go in `docs/ui-qa/screenshots/phase-4/`, and any breakage gets fixed.
- Merge into `master` (`--no-ff`). Then merge `feat/dev-mfa-switch`, resolving conflicts in the main session (probably `AppShell`, `AuthContext` and the e2e helpers). Re-run `login.spec.ts` after that merge.

### 3. Small gaps from v2 (new branch `feat/v2-gaps`, subagents allowed under section A)
- Show the user's name in the header, not the Keycloak UUID.
- A remove-project-member endpoint and UI: lead_estimator and above, audited, with tests for the lowest allowed role and a denied role. The backend part is main session only.
- Fix the `NavLink` `end` double highlight.
- Make `make dev-simulate-settlement` idempotent, so no e2e test skips because of leftover state.
- A `platform_admin` demo user, dev and test only, created under the same `APP_ENV` guard as the other demo users (main session only).
- `CostRateComponentOut` / `CostItemRateOut` switched to `JsonDecimal`.

### 4. Phase 5: final regression and report (main session only)
- Nothing else may be using the stack. Run **one clean full run** of `make test-all`, then `npm run build && npm run test && npm run lint`, then `npm run e2e` and `npm run e2e:real-backend --workers=1`, with MFA **on** for the real-backend run. **A failure is a failure until proven otherwise:** don't label anything "contention", find the cause and fix it.
- A final lifecycle walkthrough in the Playwright MCP with MFA **off**: estimator, then lead, then procurement, then bd or md, from a new project through to win/loss.
- Write `docs/ui-qa-report.md` as `docs/ui-qa-brief.md` Phase 5 specifies, plus a section confirming that every subagent branch was verified under rule A7.
- Leave the stack running with MFA **off**. Stop and report.
