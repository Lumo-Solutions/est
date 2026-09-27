# Est Build: UI QA, Gap-Fill and Redesign Brief (autonomous)

Read `docs/build-log.md`, `docs/preconstruction-build-report.md`, `docs/keycloak-setup.md` and `MASTER_SRS.MD` first. The goal is a product a real estimator, procurement head or director could use without help. That means you find and fix every broken, missing or confusing thing through the real UI, and then make the app look professional.

You run this **autonomously**: you do the thinking, testing and fixing. Keep `docs/ui-qa/log.md` current, and when resuming, read it first and continue from the first unfinished phase.

---

## 0. Rules (same spirit as the build brief)

### 0.1 Stop and ask only for:
- destructive or irreversible actions (dropping or rewriting data or migrations, force-push, deleting tracked files you didn't create);
- `deploy/.env` edits other than appending missing keys from `.env.example`;
- anything that weakens RLS, auth, MFA step-up, audit, segregation of duties, or the rule that AI output is only a proposal;
- copyleft or commercial dependencies (GPL, AGPL, SSPL, BUSL, AG Grid Enterprise, paid UI kits or fonts).

Anything else: pick the sensible option, record it in the log, and continue.

### 0.2 Hard constraints
- **Air-gapped:** no CDN, no Google Fonts links, no remote icons or images, no analytics. Fonts are self-hosted through npm (`@fontsource/*`) or bundled files. Icons come from an MIT-licensed npm package (for example `lucide-react`) and are bundled.
- **The server is the only enforcement.** The UI may hide actions a role can't perform, but it never replaces a server check. Never change a backend permission to make a UI test pass.
- **Money:** Decimal from end to end. Display AED with thousands separators, 2 dp for amounts and rates, right-aligned numbers, and 3 dp for margin wherever it drives routing (already decided). Remember that API Decimals arrive as JSON strings; parse them safely and never with a float `parseFloat` for totals.
- **Git:** one branch per phase, conventional commits, `--no-ff` merge to `master` when green, **never push**. Use `git --no-optional-locks` for read-only commands.
- **Every fix gets a regression test:** a real-backend Playwright spec (`frontend/e2e/real-backend/`) for flows, vitest for components and logic, pytest for backend changes. Every new permission gets tests for the lowest allowed role and a denied role.
- **Report pre-existing bugs separately** from new work in the log.

### 0.3 Models and subagents
You can't change your own main model, so use subagents with an explicit model for each task:
- **Opus** (main session): planning, root-cause debugging, anything touching auth, money or security, design-system decisions, and reviewing subagent output.
- **Sonnet** subagents: mechanical fixes to a clear spec, writing tests, applying the design system page by page, and responsive or accessibility passes.
- **Haiku / Explore** subagents: inventories (routes, endpoints, components), grep sweeps, and checking screenshots against a checklist.

Always review a subagent's diff yourself before committing. Never let a subagent touch auth or security files without your review.

### 0.4 Memory (earlier runs were killed by the memory guard)
- Run **one browser at a time.** Don't run the Playwright MCP browser and a Playwright test suite at the same time. Close pages and contexts when you're done with them.
- Run test suites with `--workers=1`, one spec at a time when debugging. Stop containers you don't need (the `tools`/`gpu` profiles). Check `docker stats --no-stream` before heavy runs.
- If the memory guard kills a run, reduce the footprint and **retry once**. If it's killed again, log it and move on to work that doesn't need that run, then come back to it later.

### 0.5 Using the Playwright MCP against the dev stack
- The app is at `https://localhost:8443`. The certificate is self-signed, so configure the MCP browser to ignore HTTPS errors (a launch option or config flag).
- Log in through the real Keycloak form. Compute TOTP codes from the dev-fixed secrets in `frontend/e2e/real-backend/totp.ts`, for example `node -e` with otplib. Never weaken auth to make testing easier.
- Save evidence: screenshots in `docs/ui-qa/screenshots/<phase>/<page>-<role>-<state>.png`, before and after any fix or redesign.

---

## Phase 0: finish the Keycloak step-up branch (`fix/keycloak-step-up`)
1. Run `bash deploy/keycloak/test-stepup-freshness.sh` under the memory rules above. Report which signal Keycloak 26 actually updates on an OTP-only step-up, and the result of each case:
   - (a) login, wait past the max age, then step up with OTP only: the approval **succeeds**;
   - (b) step up, wait past the max age, then approve: **step-up required**;
   - (c) a silent SSO re-authorize without `acr_values` must not produce a token that counts as fresh silver.
2. If (a) fails, fix the freshness signal (the LoA session note or a claim mapper), not the time window. Afterwards, restore the dev stack to the real 300s settings.
3. Run `make test-all` and `npm run e2e:real-backend` (with `--workers=1`).
4. **If (a), (b) and (c) pass and both suites are green, merge to `master` yourself.** If any of them fails and you can't fix it, stop and report. Don't merge.

## Phase 1: inventory and demo data
1. List every frontend route, every backend endpoint, and which roles can use each. Save it as `docs/ui-qa/coverage.md`: a matrix of page × role × action, noting which endpoint each action calls.
2. Mark every backend capability that has **no UI at all**. Likely candidates to check:
   - vendor master and duplicate review;
   - prequalification and certificates, with expiry alerts;
   - cost library, with an as-of date view and rate history;
   - project creation, editing and members;
   - users and roles (read-only, from Keycloak);
   - quotation supporting documents;
   - saved scenarios;
   - Module E read views.
3. Seed rich demo data: run `make dev-simulate-e2e`, then add enough extra data (several projects, vendors, packages and settlements in every status) that no page is only ever tested empty. Tag all of it so `make dev-clean-demo-data` removes it.

## Phase 2: functional QA of every page, as every role, through the real UI
For each page × role, walk through it with the Playwright MCP and check:
- **Navigation:** reachable from the menu, breadcrumbs and back links work, deep links and a browser refresh work, and a missing id shows a 404 page rather than a blank one.
- **Create, edit, delete:** every entity a user needs to create has a visible way to create it (for example a "New project" button). Forms validate on the client, then show server errors field by field. Success gives clear feedback and the view refreshes.
- **States:** loading, empty (with a call to action), error (with retry), long lists (pagination or virtualisation), long text, and large numbers.
- **Files:** uploads (drawings, BOQ, workbooks) show progress, errors for wrong type or size, and results. Downloads (exports, RFQ sheets) work and have sensible filenames.
- **Permissions:** actions the role can't perform are hidden or disabled with a reason. Try them anyway through the API or a direct URL to confirm the server refuses. Step-up fires, completes and retries properly. SoD is visible (you can't approve your own submission).
- **Workflow continuity:** after each step there's an obvious next step. For example: BOQ imported, so "Reconcile"; quote accepted, so "Level bids"; settlement approved, so "Export".
- **Browser console and network:** no uncaught errors and no failed requests during normal use.

Log every issue in `docs/ui-qa/issues.md` with an id, page, role, steps, expected vs actual, severity (P0 broken or blocking, P1 wrong or confusing, P2 polish) and screenshot.

**Fix P0 and P1 as you go**, each with a regression test. Leave P2 for Phase 4.

## Phase 3: fill the gaps (missing screens and workflows)
- Build UI for every capability marked "no UI" in Phase 1 that a real user needs: vendor master, duplicate review, prequalification and certificates, cost library, project creation, editing and members, and anything else the matrix shows.
- Add backend endpoints only where a screen genuinely needs one. They follow the existing patterns: RLS, audit, role tests. No schema changes to security tables.
- Also cover the build report's known UI gaps:
  - per-trade and per-line simulation overrides in the cockpit;
  - replace every `window.prompt` and `window.confirm` with proper modals;
  - a delete action for saved scenarios (add the endpoint);
  - a usable taxonomy tree editor.
- Add a **home dashboard per role** that answers "what needs my attention?". Examples: approvals waiting for me, quarantined mail, quotes to review, certificates expiring, RFQs past due, settlements in draft.

## Phase 4: design system and redesign (use the `ui-ux-pro-max` skill)
1. Load the `ui-ux-pro-max` skill. If it isn't available, log that and use your own design judgement with the same deliverables.
2. Write `docs/ui-design-system.md` **first**:
   - **Product style:** professional enterprise B2B for construction estimating and procurement. Dense but calm, data-first, built for long working sessions.
   - **Tokens:** colour (neutral base, one brand accent, semantic success, warning, danger and info, all WCAG AA), typography (a self-hosted sans for UI and tabular figures for numbers), spacing, radius, elevation.
   - **Components:** app shell (sidebar with project context, top bar, user and role menu), buttons, forms, tables and AG Grid theme, tabs, modals, drawers, toasts, badges for every status (draft, submitted, approved and so on), empty states, skeleton loaders, the step-up prompt.
   - Keep everything in Tailwind tokens and theme variables with no one-off colours. Light theme required; dark theme optional.
3. Apply it to every page, using Sonnet subagents page by page with your review. Fix every P2 item from Phase 2 along the way.
4. **Layout targets:** 1440 and 1280 wide as the primary sizes, and still usable at 1024. The drawing split view and the big grids must stay fast (keep the 5,000-row test green).
5. **Accessibility:** full keyboard navigation, visible focus, labels on every input, AA contrast, and aria attributes on custom widgets. Run axe (via `@axe-core/playwright`, MIT) on every page with no serious or critical violations.
6. Save before and after screenshots of every page.

## Phase 5: final regression and report
- `make test-all`, `npm run build`, `npm run test`, `npm run lint`, `npm run e2e` and `npm run e2e:real-backend` (`--workers=1`), all green.
- A final Playwright MCP walkthrough of the full lifecycle as the correct roles in turn: estimator, then lead, then procurement, then bd or md.
- Write `docs/ui-qa-report.md` covering:
  - the coverage matrix (every page × role, tested yes or no);
  - issues found and fixed (by severity), and pre-existing bugs listed separately;
  - new screens and endpoints;
  - the design system summary with before and after screenshot links;
  - axe results;
  - known gaps and anything that needs my decision;
  - final test counts;
  - the exact commands for me to verify.
- Stop there. I'll review and test by hand.

## After each phase
Update `docs/ui-qa/log.md` and print a status block of no more than 10 lines: phase, merge status, issues found and fixed, new tests, counts, and anything that needs my decision. Then continue to the next phase.
