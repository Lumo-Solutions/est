# Est Build: Handoff Summary 2 (covers 26 Sep – 8 Oct 2026, updated 10 Oct 2026)

Context for the next chat. This continues `claude/handoff-est-build.md` (the first handoff, up to 26 Sep). Read that one for the original stack, environment, ports and working rules. This document covers everything since then.

**Current state (checked in the repo on 10 Oct):** `master` is at **a7f3825** ("Merge fix/intake-scale"). Nothing has been pushed. The working tree is clean apart from the untracked `.claude/` and `docs/handoff-est-build-2.md`. **The index-speed work (§2.7) has not started.** Whether the user resumed the two paused packs after 8 Oct is **unknown**: ask them, or check the packs in the app.

---

## 1. How we work (unchanged, plus additions)
- The user runs **Claude Code** locally in `C:\Users\mdabd\Documents\est build` (Windows, Git Bash, Docker Desktop). Claude in claude.ai acts as **reviewer and architect**: it writes briefs, reviews reports, and spot-checks the repo through the device bridge (read-only git: always use `git --no-optional-locks`, which avoids leaving a stale `.git/index.lock`).
- **Large tasks go in as brief files in `docs/`.** The user pastes a one-line "Read docs/X.md and execute it" prompt. Briefs written so far:
  - `preconstruction-build-brief.md`;
  - `ui-qa-brief.md`;
  - `finish-brief.md`, whose **section A holds the subagent control rules**;
  - `tender-intake-brief.md`;
  - `ai-provider-brief.md`.
- **Subagent control rules** (`finish-brief.md` §A), mandatory for every task:
  - only the main session merges, switches branches or commits to master;
  - subagents work in `isolation: worktree` on `agent/<task>` branches, with a file allow-list and a forbidden list;
  - subagents never touch the shared dev stack;
  - security files are main-session only;
  - at most 2 subagents at a time, and a finished subagent is never resumed;
  - the main session verifies that commits exist, reads the diff and re-runs the tests before accepting anything.

  These rules exist because subagents once merged a phase on their own, restyled pages they weren't assigned, and invented commit hashes.
- **Git:** a branch per feature, `--no-ff` merges to `master`, conventional commits. **Nothing has ever been pushed.** A private GitHub repo is recommended. Before pushing: confirm `deploy/.env`, `s3-identities.json`, `.dev-token` and `deploy/vendor/` are ignored, **and that `.claude/` is gitignored and purged from history.** It was committed by mistake and then removed, so it's still in history.
- **Memory is the main operational constraint.** Full test suites and big runs get killed by the host's memory guard. The pattern is now:
  - run each suite separately;
  - run real-backend Playwright specs one at a time with `--workers=1`;
  - never run the MCP browser and a test suite together.

  A `.wslconfig` (memory=10GB, processors=6, swap=4GB, assuming 16 GB of RAM; **the user's RAM was never confirmed**) was recommended to cap Docker. To kill the Docker VM, use `wsl --shutdown`; Task Manager can't end VmmemWSL.

## 2. What was built (all on `master` unless noted)

### 2.1 Pre-construction programme (Phases 1–9, `docs/preconstruction-build-brief.md`)
- **D1, settlement:**
  - rates are authoritative (line = rate × qty, with `rounding_difference` at settlement level);
  - SoD: the submitter can't approve. This fixed a real gap in the generic approval engine;
  - statuses: draft → submitted → approved/rejected → won/lost;
  - a quantity check at submit, plus "refresh quantities";
  - boundary tests (AED 2,000,000.00/.01, 8.00%/7.99%, zero total, negative markup).
- **D2:** generated export with a leak test, original workbook retained at import, win/loss with reason codes.
- **D3:** export into the client's original workbook, with an observed fidelity report. Refused if anything would be lost, unless `accept_loss` is set.
- **Module B:**
  - vector PDF geometry;
  - multi-signal scale detection and two-point calibration;
  - non-destructive overrides;
  - bbox traceability;
  - layer → trade mapping;
  - typology clustering (DXF blocks, and a translation-only hash for PDF).
- **Phase 5:** semantic matching with pgvector and a feedback table (embedding model via `make download-embedding-model`).
- **Module C:** vendor location matching, subtotal/unit/FX checks, exclusion citations.
- **Module E:** schema only (contracts, revisions, exclusion register, outturn write-back).
- **Frontend:** React 18, Vite, Tailwind, AG Grid Community. BFF cookie auth with PKCE and CSRF, and step-up handling.
- **`make dev-simulate-e2e` / `make dev-clean-demo-data`.**

### 2.2 Security and auth fixes
- **Keycloak step-up (LoA flow `browser-stepup`):**
  - bronze = password + TOTP;
  - silver = TOTP re-entered within 300 s;
  - the backend's `has_recent_step_up` checks acr AND `auth_time` freshness, proven against real Keycloak;
  - `prompt=login` removed so step-up is OTP only;
  - the account console is disabled (the admin runbook is in `docs/keycloak-setup.md`).
- **Dev login over HTTPS:** `caddy-dev` at **https://localhost:8443**, with a self-signed certificate the user imported into Windows.
- **Dev MFA switch:**
  - `DEV_DISABLE_MFA` is only honoured when `APP_ENV` is exactly `dev`/`test`; the backend refuses to start otherwise;
  - it covers login AND step-up, and every bypass is marked `mfa_bypassed_dev` in the audit log;
  - a "DEV: MFA disabled" banner shows;
  - `make dev-mfa-off` / `make dev-mfa-on`.

  **The user tests with MFA off.**
- **Fail-closed bootstrap:** demo users, known passwords and fixed TOTP secrets are only seeded in dev/test.
- **Logout:** it now ends the Keycloak SSO session (back-channel logout, a 303 to end-session, a top-level form POST), and lands on `/signed-out`.
- **Approval routing:** uses Decimal end to end; margin is shown to 3 dp.
- **Project creation:** bd_director, managing_director **and lead_estimator** (migration 0029).
- **Production:** `docker-compose.prod.yml` must set `APP_ENV=production`. This was flagged; check that it was done.

### 2.3 UI QA, gap-fill and redesign (`docs/ui-qa-brief.md`, `docs/v2.md`, `docs/ui-qa-report.md`)
- Every page tested as every role. Fixes include 404s, retry loops, role gates and JsonDecimal.
- **New screens:**
  - vendors, duplicates and certificates;
  - cost library and as-of history;
  - Module E read views;
  - project members (add and remove);
  - quote attachments and FX;
  - per-trade and per-line overrides;
  - taxonomy tree editor;
  - modals instead of `window.prompt`;
  - a role dashboard.
- **Approvals inbox:** dashboard rows link through; `/approvals` and `/approvals/:id` pages; cost_rate_change decisions; orphaned approvals hidden.
  - **Still open:** `POST /approvals/{id}/decide` does not sync the bid settlement's status.
- **Design system, then the Figma redesign** (`feat/figma-ui`, merged). IBM Plex Sans self-hosted, lucide-react bundled, axe 18/18, and an air-gap guard test (no remote URLs in `src/`).
- **Drawing pipeline:** never stuck any more (partial/failed with reasons, a sweeper, Retry extraction). nginx serves `.mjs` correctly, so the PDF viewer works.

### 2.4 Tender intake (`docs/tender-intake-brief.md`, then AI-first)
- Drop a folder or zip, with C2-grade safety (zip bombs, macros, encryption, nesting), sha256 dedupe, classification, routing:
  - drawings → extraction;
  - BOQ → the import wizard, pre-filled;
  - addenda → a register with supersede links, flagging draft settlements;
  - everything else → a document register.
- **AI-first intake** (`feat/ai-first-intake`, merged at 27ee650):
  - **one project page** (a header with an Edit drawer, a drop zone, an organised document tree);
  - the AI classifies every file (rules are hints and the fallback);
  - drawings get discipline, type, number, revision and villa type;
  - auto-accept at ≥ 85% confidence (an admin setting); a "Needs your check" list; reclassify at any time, which undoes routing.
- **PDF BOQ import:** pdfplumber first, then AI vision for pages it can't parse, through the same wizard.
- **DWG support:** done through **ODA File Converter (Linux .deb 27.9 in `deploy/vendor/oda/`, gitignored)** in a sandboxed `dwg-converter` container. This knowingly deviates from the SRS "no ODA" line; check the licence summary in `docs/deploy-deltas.md`. Samples are in `deploy/vendor/oda/samples/` (2 villa DWGs, AC1032).

### 2.5 External AI provider (scope change, the user's decision; `docs/ai-provider-brief.md`, `docs/ai-report.md`)
- **The SRS's "no external AI" rule is temporarily reversed** until a GPU server runs the in-house model. Switching back is configuration only.
- **`AIProvider`:** `local_vllm` | `anthropic` | `openai_compatible` | `mock`.
  - **Governance:** an "External AI allowed" switch (MD only, off by default) plus a per-project opt-out; an `ai_calls` audit table; monthly and per-project USD budgets as hard stops; a cache by sha256; rate limiting; prompt-injection tests; no action fields; the AI never computes money.
- **Features:**
  - the AI classifies intake files;
  - it reads PDF BOQs, drawing annotations and title blocks;
  - **verification report:** for each BOQ line, Match / Variance / Missing in drawings / Not verifiable, plus Missing in BOQ. Quantities come only from measured geometry or annotations; an AI estimate is never used as a quantity. Exports to xlsx and PDF;
  - **pricing assistant:** proposes a cost from quotes, the cost library or history with a rationale and flags, and suggests a markup range. A person accepts and sets everything.
- **Mock data:** `make dev-seed-ai-demo`, `make dev-ai-demo-pack` (writes `.ai-demo-pack/`), `make ai-eval`, `make ai-smoke`, `make check-ai-env`.
- **The user's `.env` is set to Qwen through Alibaba Model Studio (international):**
  - `AI_PROVIDER=openai_compatible`
  - `AI_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
  - `AI_MODEL=qwen3.7-plus` (vision and reasoning), `AI_MODEL_CLASSIFY=qwen3.7-flash`
  - The key is in `.env` only.
- **Real Qwen cost, measured from the bill:**
  - `qwen3.7-flash` costs about **$0.03 per million input tokens, $0.006 cached, $0.13 output**;
  - 9 calls cost about $0.012, while the app's estimate said $0.70 (it uses a cautious default for unknown models);
  - **No `qwen3.7-plus` call has appeared on the bill yet**, so the plus path is unverified;
  - Alibaba's "$10 spending alert" only alerts; the app's budgets are the hard stop.
- **Possible Qwen gotcha:** if structured output fails, the "thinking" mode is the cause. Add `AI_EXTRA_BODY` → `{"enable_thinking": false}` to the openai_compatible provider.

### 2.6 Scale incident and fix (`fix/intake-scale`, **status unknown**)
- **The incident:** a real **1,600-file** folder crashed the upload at about 520 files and took Docker down.
- **Root causes:**
  - whole uploads were buffered in memory;
  - one task fanned out 16 files at a time;
  - there were no container memory limits;
  - queue messages were lost in the crash;
  - **pdfplumber on CAD PDFs:** an 8 MB A0 sheet took 163 s and 3 GB.
- **Fixed on the branch:**
  - resumable, browser-hashed, streamed uploads (4 files in flight);
  - DB-driven per-file tasks with size, page and time limits;
  - memory and CPU limits on the workers;
  - Pause / Resume / Cancel;
  - a sweeper;
  - a virtualised list and server-side "Confirm all";
  - the CAD PDF now takes 2.4 s and 0.4 GB.
- **The proof run:** 2,051 files on mock, with resume after an upload kill and after a worker kill. **The drawing measurement stalled at 114/898.**
- **The last prompt sent (1 Oct) asked for:**
  - **on-demand drawing measurement** (index all, measure only when opened, needed by verification, or selected by discipline, via a priority queue), plus a stall diagnosis;
  - real Qwen rates in `pricing.py` with cached-token pricing;
  - a **cost estimate plus a confirm step before resuming or starting a pack**;
  - `.wslconfig` docs; a SeaweedFS memory limit; Postgres tuned (no hard limit);
  - each suite run separately; merge; restore the stack to the user's `.env`; **don't resume the packs.**
- **The user's crashed packs, both paused:**
  - **project 102, pack 948b4c0f:** 1,588 files, 2.7 GB, fully uploaded, needs reading;
  - **project 103, pack 661d42e3:** 560 files; re-drop the folder to resume the upload.

  44 files had been mistakenly classified by the mock; they were reset.

## 3. Current environment facts
- **The stack** runs with `make up` (`deploy/docker-compose.yml` + `override.dev.yml`). Afterwards: `make migrate`, then `make bootstrap-keycloak` (idempotent, keeps MFA off).
- **App:** https://localhost:8443. Hard-refresh after frontend rebuilds (the index.html no-cache fix is in).
- **Demo users** (password `<Name>1Pass!`): estimator1, lead1, procurement1, bd1, md1, plus admin1 (platform_admin). Dev TOTP secrets are in `frontend/e2e/real-backend/totp.ts`, but they aren't needed while MFA is off.
- **Pending stops:** if the workers are stopped, they are started by `make up`.

## 4. Open items and next steps
1. **Check whether `fix/intake-scale` finished and merged.** If not, re-send the 1 Oct prompt (in this chat's history, and summarised in §2.6).
2. **The user's next actions, after the merge:**
   - apply `.wslconfig`, run `wsl --shutdown`, restart Docker, run `make up`;
   - run `make ai-smoke`, confirm a `qwen3.7-plus` row on the Alibaba bill, and report its rate;
   - resume pack 102 after checking the cost estimate;
   - re-drop the folder for pack 103.
3. **Known bugs and gaps:**
   - the API test `test_include_arbitrary_evidence_and_dimension_guard` failed once with `KeyError: '1.4'` (unexplained);
   - `POST /approvals/{id}/decide` doesn't sync the settlement status;
   - the full real-backend suite has never had one clean uninterrupted run since the AI work (memory); individual specs pass.
4. **Before the first push:** purge `.claude/` from history and gitignore it; create a private GitHub repo.
5. **Product decisions still open:**
   - client acceptance of a generated BOQ versus their original workbook;
   - confirm the AED 2m / 8% thresholds with the MD;
   - validate the invented DXF layer conventions and the 2% tolerance on real drawings;
   - the confidentiality of sending tender data to Alibaba (check tender terms; use the per-project AI opt-out);
   - should cost_rate_change go through approval at all;
   - the ODA licence for server use.
6. **Later roadmap:** a real-tender accuracy review of the AI (classification, verification, pricing); security hardening (encryption at rest, `AUDIT_ALL_READS`, rotating secrets); the GPU server on Contabo with local vLLM (then switch `AI_PROVIDER` back); backups; production deployment.

## 5. Key docs in the repo
- **Original handoff list:**
  - `MASTER_SRS.MD`;
  - `docs/deploy-deltas.md`;
  - `docs/keycloak-setup.md`;
  - `docs/takeoff-pipeline.md`;
  - `docs/boq-reconciliation.md`;
  - `docs/procurement-*.md`;
  - `docs/module-d*-plan.md`.
- **Plus:**
  - the briefs listed in §1;
  - `docs/build-log.md`;
  - `docs/preconstruction-build-report.md`;
  - `docs/ui-qa-report.md` and `docs/ui-qa/` (coverage, issues, log, screenshots);
  - `docs/v2.md`;
  - `docs/ui-design-system.md`;
  - `docs/figma-implementation-plan.md`;
  - `docs/tender-intake-report.md`;
  - `docs/ai-plan.md`, `docs/ai-report.md`, `docs/ai-provider.md`;
  - `docs/ai-first-intake/report.md`;
  - `docs/intake-scale/report.md`.
