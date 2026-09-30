# AI-first intake and the one project page: report

Branch `feat/ai-first-intake` (from master after `feat/ai-provider`). Build log: `docs/ai-first-intake/log.md`. Rules: `docs/finish-brief.md` section A.

## What a user gets

- **One project page.** A compact header (code, name, client, tender ref, location, members) and an **Edit project** drawer (location, "keep off external AI", members). The Overview / Tender documents tabs are gone; old `?tab=` URLs redirect, the nav item is now "Project", and the old "Drawings" nav link goes to the project page.
- **Empty project:** a large "Drop your tender folder or zip here" zone (folder drag, Choose folder, Choose files, zip). **With files:** live reading progress, **Needs your check** at the top, **Next steps** (Import BOQ, Open drawings / takeoff, Run verification report, Build settlement), and the organised document tree (class > discipline > drawing type, counts, confidence, status, AI / rules / You, original-folders toggle, search, filters, bulk change class).
- **The AI reads every file first.** Filename, folder, file type, the first two pages of text (or a workbook's sheet names and first rows) and, only when the text is not enough, a page image plus a title-block crop for the vision model. The rules' findings go in as hints and are the fallback ("Classified by rules"). Output is a strict schema: class, discipline (11), drawing type (7), villa type, number / title / revision / sheet / scale, addendum number / date / supersedes / amends, confidence, evidence quote and page. No action fields.
- **Automatic acceptance.** At or above the tenant threshold (default 85%, `managing_director` changes it on the AI admin screen, audited) a file is accepted and routed: drawings to extraction / DWG conversion, BOQ to "ready to import" with sheet, header row and columns pre-detected, addenda to the register with supersede links, the rest to the document register. Below it, or with a conflict or suspected injection flag, it waits under Needs your check (one-click Confirm or Change).
- **Reclassify at any time.** Routing follows: a drawing reclassified as a spec leaves the takeoff (archived, measurements kept, BOQ reconciliation recomputed) and comes back if changed again; an addendum is withdrawn from the register (never deleted) and revived if routed again. Every step is audited with who decided (`ai`, `rules`, `user`).

## Decisions worth knowing

- `sub_type` now holds the fine discipline; drawing type and villa type live in `metadata`. Legacy `civil_infra` / `other` stay valid.
- Documents are read in groups of 16 with 4 AI calls at a time. A not-configured / not-allowed / over-budget result, or 3 failures in a row, stops AI calls for the rest of the run (no hammering the gateway) and the rules decide. A byte-identical copy in the same project reuses its original's answer (no second call); the gateway's own sha256-keyed cache covers re-runs on external providers.
- Files classified by the rules are never auto-accepted (nothing is routed on the rules' say-so alone, as before).
- Auto-accept routing runs as the system actor (addenda are a lead_estimator-and-above write); the audit payload says `decided_by: ai` and records the threshold.
- Migration `0037`: threshold column, `classified_by` / `auto_accepted`, `drawings.archived_*`, `addenda.withdrawn_*`. Deploy notes are in `docs/deploy-deltas.md`; the data-flow table in `docs/ai-provider.md` was updated (every file is now sent, not only uncertain ones).

## Verification (each suite run separately)

| Suite | Result |
|---|---|
| Unit | 682 passed (full run); the files touched afterwards re-ran green |
| Integration, AI-first + old flow + RLS | 38 passed; `test_ai_first_intake.py` alone later 21 passed (incl. the context-binding regression) |
| Integration, full directory (one earlier run) | 262 passed, 2 failed with asyncpg connect timeouts under heavy load; both pass when run by name (13 s) |
| API (`tests/api`) | 94 passed (after fixing my own test: the shared test client changes identity on every call) |
| ai-service prompt contract | 19 passed |
| Frontend | tsc clean, oxlint the 3 pre-existing warnings, vitest 32 files / 213 tests, mocked Playwright 5 passed |
| Real-backend, mock provider, `--workers=1`, one spec at a time | `ai-first-intake` 4/4, `tender-intake` 4/4 (a 338-file pack included), `ai-walkthrough` 2/2, `project-pages` 9/9, `layout-widths` 1/1 |

Coverage asked for: mock fixtures for all 12 classes, all 11 disciplines and all 7 drawing types; a drawing in a "BOQ" folder (and a BOQ in "Drawings") follows its content; auto-accept above and below the threshold (75 / 85 / 95%); drawing > spec undoes takeoff and back; AI not configured / not allowed / over budget / failing falls back to rules; prompt injection in a PDF (a resisting model and a "compromised" one that returns action keys); a 300-file pack with bounded concurrency; the real-backend walkthrough (create project, drop `.ai-demo-pack`, groups, confirm the one low-confidence file, drawings ready, BOQ wizard pre-filled, dry run, commit).

## Found while building (all fixed, with tests)

1. **PDFium is not thread-safe.** Rendering page images from concurrent threads crashed pytest with a segfault. Rendering is behind a lock (see memory note).
2. **The concurrent AI phase had no request context bound** (the gateway reads it). Unit and integration tests missed it because their gateways carried a fixed context; the real stack showed every file as "classified by rules". Fixed and a regression test added that uses a gateway without a fixed context.
3. **Addenda have no DELETE policy**, so un-routing one silently did nothing; they are now withdrawn with a flag.
4. The demo pack's "approve"-word false positive in the mock (BOQ descriptions say "approved fill") made BOQ files look steered; the mock now needs an instruction-shaped phrase.

## Things to know

- I extended the demo pack (`make dev-ai-demo-pack` writes `./.ai-demo-pack/`, now 9 files): a stormwater plan-and-profile sheet filed under the BOQ folder, and a site-visit note the AI cannot classify (the one "Needs your check" item).
- The e2e runs used `AI_PROVIDER=mock` as a shell-only override of `make up`; `deploy/.env` was never edited. The stack was then recreated without it: backend and workers report `AI_PROVIDER=openai_compatible`, `AI_MODEL=qwen3.7-plus`, `AI_MODEL_CLASSIFY=qwen3.7-flash` (as in your `.env`), `DEV_DISABLE_MFA=true` (MFA off), and `make check-ai-env` passes. Nothing I ran called the external provider: the `ai_calls` rows with cost (225, about $14.93) are from 20:34-21:03 UTC, before this session started.
- The admin usage view is month-to-date, so the `ai-walkthrough` spec now checks only the mock rows for zero cost.
- One `test_verification_api` failure appeared once in a full API run (`KeyError: '1.4'`) and did not reproduce in two later runs, one of them a full run; I did not establish its cause. The same run had my own failing API tests before their fix.
- Headings: the project title appears in the top bar and is not repeated in the header card.
- Known limit: "Confirm all shown" covers the rows on screen (25 at a time), not every needs-check file.
- Not pushed.

## Process record (finish-brief section A)

Two Sonnet subagents (`intake-admin`, `intake-tree`), each with a file allow-list and forbidden list, in worktrees I created by hand from the branch head. For both: commits confirmed to exist, diffs limited to the allow-list, tsc / oxlint / vitest re-run by me, merged `--no-ff` by me. Nobody pushed. I also launched an empty `Workflow` by mistake (no agents ran).
