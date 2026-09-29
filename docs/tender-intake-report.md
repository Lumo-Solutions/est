# Tender intake and approvals inbox: report

Brief: `docs/tender-intake-brief.md`. Plan: `docs/tender-intake-plan.md` (with an "as built" section). Log: `docs/tender-intake/log.md`.
Branches: `fix/approvals-inbox` (Part 1, merged earlier) and `feat/tender-intake` (Part 2).

## Part 1: approvals you can act on

- The "Approvals waiting for me" tile rows are links and show project code and name, a readable type ("Bid settlement v3", "Cost rate change"), the amount, margin on sell (3 dp) for settlements, who submitted and when, and the role it waits on. "View all" and a sidebar "Approvals" link go to a new `/approvals` page (pending for me, decided by me in the last 30 days).
- Approve and reject happen on the entity's own page: the settlement cockpit for settlements, and a new `/approvals/:id` decision page for everything else. Reject asks for a reason in a modal. SoD, step-up (or the dev bypass and its audit flag) and server-side role checks are unchanged.
- **Found and fixed:** rebuilding a settlement version leaves the old version's approval request pending forever, and each of those orphans linked to the *current* settlement for every approver. The inbox and the tile now hide requests whose settlement is no longer the current submitted one.
- **`cost_rate_change`:** nothing in the app creates these requests (recording a rate applies immediately), and there was no UI to decide one. The decision page now handles them; the tests create them through the generic `POST /approvals`. Whether a rate change should really go through approval is a product decision I did not make.
- **Deviation:** the brief has lead1 submitting a settlement, but only bd_director and managing_director can submit, so the spec is bd1 submits, md1 approves.
- **Left alone (security-sensitive file, rules must stay):** the generic `POST /approvals/{id}/decide` still accepts a bid settlement's request without syncing the settlement status. The UI never calls it that way.

## Part 2: tender document intake

What a user gets: a "Tender documents" tab on the project. Drop loose files or a .zip (up to 60 MB a file, 300 files a request, larger drops go in batches into one package). A worker checks each file, expands archives, extracts metadata and proposes a class. A lead_estimator or above confirms (one by one, in bulk, or "confirm high-confidence"), and confirming routes the document.

| Class | Where it goes on confirm |
|---|---|
| Drawing (DXF, vector PDF) | A `Drawing` row in the existing pipeline (content-addressed, no copy), ingest triggered, number/revision/discipline attached, revision lineage (`supersedes_id`). Scanned or raster: flagged not measurable. DWG and images: stored and flagged "convert to DXF/PDF", no drawing created. |
| BOQ | The import wizard opens pre-filled (sheet, header row, column mapping, the original workbook fetched same-origin). The user still runs the dry run, then commits; retention of the original is unchanged. |
| Addendum | Addenda register (number, date, what it supersedes or amends, each link resolved against routed documents). Draft or submitted settlements of the project are flagged, and the settlement page shows a banner ("Refresh quantities before you submit" for a draft, re-review for a submitted one). |
| Everything else | Project document register: stored, revisioned, searchable by metadata, downloadable (audited). Contracts sit there with class `contract`; nothing is written into Module E tables. |

Safety (extends the C2 layer): allow-list pdf, dxf, dwg, xlsx, xls, csv, docx, doc, jpg, png, zip; content sniffing (ASCII DXF is no longer mistaken for csv); `.xlsm`/`.docm` and macros in a zip rejected; encrypted PDFs, encrypted Office files and encrypted zip members rejected; zip bomb (ratio checked before size, entry count, per-entry and total limits), nesting depth 2, traversal/absolute/drive-letter names reject the whole archive, and no member name is ever used as a filesystem path. All of it runs in the worker with a soft time limit and a per-document budget; one failing document is recorded on that document and never stops the rest.

Classification: deterministic rules first (file type, xlsx header sniff, PDF/DOCX text and title-block regexes, filename patterns, vector density), evidence recorded with the matched text. The local model (guided JSON, no action fields, prompt-injection boundary) only runs for low confidence or conflicting rules, with the page image only when there is no text layer. A model failure never fails a document. Nothing is routed without confirmation.

Data: migration `0030` (packages, project_documents, document_classifications, addenda, addendum_links, tender_class_config, `drawings.supersedes_id`), RLS enabled and forced on every table, project scoped except class config, every state change audited.

## Verification

| Check | Result |
|---|---|
| `make test-all` | unit 473, integration 230, API 62, all passed (one run) |
| Intake unit tests | archive safety, per-file safety, every rule, metadata regexes, addendum reference parsing, revision ordering, classifier and prompt boundary, accuracy on the pack |
| Intake integration/API tests | RLS enabled+forced, tenant isolation and project scope on all six tables, write roles per table, upload roles (estimator allowed, non-member and platform_admin denied), confirm/reclassify/edit/exclude/re-run/bulk (estimator denied, lead allowed), class admin (MD only), caps, download and content endpoints, audit events, duplicate linking, routing of every class, lineage, addendum links, settlement flags, worker failure isolation |
| ai-service prompt contract | 17 passed |
| Frontend | `npm run build` clean, vitest 78 passed, oxlint only the 3 pre-existing warnings, mocked `npm run e2e` 5 passed |
| Real-backend e2e (`tender-intake.spec.ts`) | tender flow (drop the pack, proposals, bulk-confirm, drawings `ready`, BOQ wizard pre-filled then dry run and commit, addendum revision and settlement flag, register download, axe, layout at 1440/1280/1024), admin class rename/disable/restore, and a 338-file pack (paged, virtualised, bulk-confirmed) |
| Full `npm run e2e:real-backend --workers=1`, MFA on | **No single fully clean run was achieved.** See "Final run" below. |

Classification accuracy on the synthetic pack: rules only 18/19, rules plus mock model 19/19. **These numbers are a regression baseline, not evidence of real-world accuracy:** the pack is ours and the rules were tuned while looking at it. The real-model accuracy run and a run on a real tender pack stay on the GPU checklist.

## Final run (real backend, MFA on): what happened, exactly

- **Run 1: 87 of 88 passed.** The one failure was `tender-intake.spec.ts`: the A-201 drawing ended `partial`. Cause: `embed_sheet` failed with "ONNX embedding model not found at `C:/Program Files/Git/models/...`". `deploy/keycloak/dev-set-mfa.sh` (behind `make dev-mfa-on/off`) sources `deploy/.env` with `set -a`, and Git Bash rewrote `ONNX_MODEL_DIR=/models` into a Windows path when it launched `docker compose up -d`, so every container it recreated could not find the embedding model. This predates my work (containers created hours before it show the same value) and would also make drawings `partial` for anyone using those targets from Git Bash. **Fixed** in that script (path conversion disabled for the compose call); backend and workers now have `/models`. The spec then passed under MFA.
- **Run 2 (after the fix): 75 passed, 13 failed.** The failures were `ECONNRESET` (9), `net::ERR_TIMED_OUT` (2) and two consequences of them, all from the test client to `localhost:8443`, spread across unrelated specs. No container restarted, nothing was OOM-killed, and the proxy logged a single upstream reset. I could not prove the cause. Host memory was under pressure later in the session (the harness killed a background command for it), which is the likeliest explanation, but that is a guess. **All 13 failed tests pass when re-run** (18 tests in six files, then 9 in four files including both intake specs), with MFA on.
- **Run 3** was meant to give the single clean pass, but the harness killed it for low memory before it started, and I did not restart it. So the honest summary is: two full runs (87/88 with a real bug found and fixed, 75/88 with connection-level failures) and every failing test re-run green, not one uninterrupted 88/88. A full run on a machine with free memory is the outstanding check.
- MFA has been switched back **off** (`make dev-mfa-off`, using the fixed script).

## Process record (finish-brief section A)

- Two subagents, both Sonnet, each with a file allow-list and forbidden list. Rule A7 was applied to both: the commits were confirmed to exist, the changed-file list was compared against the allow-list, and the checks were re-run by the main session before merging.
  - `agent/intake-fixtures` (commit d5418b8): two files, as allowed. The main session fixed one thing it got wrong (openpyxl stamps `modified` inside `save()`, so the pack was not deterministic).
  - `agent/intake-ui` (commit 8ab7986), in a worktree the main session created from the feature branch: 18 files, all allow-listed. tsc, oxlint and vitest re-run by the main session matched the report. Later fixes (column virtualisation off, resumable upload, admin tab) were made by the main session.
- The first worktree the harness created for a subagent was based on an old commit (4f14f8a, 23 commits behind), so the second one was created by hand from `feat/tender-intake`.
- One read-only Explore subagent mapped the existing code before planning.
- Nobody pushed. All merges and branch operations were done by the main session.

## Things to know

- **Rebuild after pulling:** prompts and schemas are baked into the backend image. Run `docker compose ... up -d --build backend celery-worker vllm` and `make migrate`. Without the rebuild the worker's model stage reports `model_unavailable` (stage 1 still works).
- The dev stack's `uvicorn --reload` can reset a connection if backend files change during an upload; the upload panel now resumes with only the unsent files.
- Duplicates: whichever of two identical files arrives first is the original; the other is flagged and linked, and stores no second object.
- Not built (by design, per the brief): no new workflows for contracts, specs and the rest; DWG, `.doc` and `.xls` are stored and classified from the filename only (no parser is installed); the real-model accuracy run.
- Known limits: the review grid scrolls horizontally inside its card at narrower widths; the "Superseded" badge in the document register only considers the current page of results.
- MFA is left off, as asked.
