# Tender document intake: plan

Brief: `docs/tender-intake-brief.md` Part 2. Branch `feat/tender-intake`. Log: `docs/tender-intake/log.md`.
This plan records every default I picked so nothing is left to be asked. Built on the code map in the
log (existing `attachment_safety.py`, takeoff pipeline, BOQ import, S3 helper, Celery, vLLM client).

## 1. Shape of the feature

```
upload (API, estimator+)                        worker (queue `ingest`, task `process_tender_package`)
  sniff size caps, project access                 per document, own time limit:
  store original in S3 by sha256                    safety check  -> (zip: expand, depth<=2, children)
  package + project_documents rows (`received`)     text/metadata extraction
  dispatch task  ------------------------------->   stage 1 rules -> stage 2 model if unsure/conflict
                                                    write document_classifications, set `proposed`
review (lead_estimator+ confirms)                 
  confirm / bulk-confirm / reclassify / edit / exclude / re-run
  confirm  ==> routing (inline, in the same transaction)
       drawing  -> Drawing row (existing pipeline, ingest triggered), lineage
       boq      -> retained, wizard opens pre-filled (sheet + header row)
       addendum -> addenda register, supersede links, settlement flags
       others   -> project document register (versioned, searchable, downloadable)
```

Nothing is routed until a lead_estimator+ confirms. Upload never creates drawings or BOQ items.

## 2. Roles

| Action | Roles |
|---|---|
| Upload, list, view, download | estimator, lead_estimator, procurement_head, bd_director, managing_director (project access via `assert_can_see_project` / RLS) |
| Confirm, bulk-confirm, reclassify, edit metadata, exclude, re-run, class admin read | lead_estimator, procurement_head, bd_director, managing_director (the "lead_estimator+" tuple, written out; no rank comparison exists) |
| Class configuration (admin) | managing_director |

Reading is any authenticated project member (RLS is the boundary). "Lowest allowed" tests: estimator for upload, lead_estimator for confirm.
Denied: estimator for confirm; a non-member estimator for upload.

## 3. Data model (migration `0030_tender_intake`, RLS ENABLE + FORCE on every table)

All tables are `TenantEntity` with `project_id` denormalised and `project_scoped=True` policies (`app_can_see_project`).
Write roles for the 5 tables below are the five business roles, except `addenda` and `addendum_links`
(lead_estimator+, because only confirmation writes them). No deletes.

- `tender_packages`: `project_id, label, transmittal_ref, received_date (date, default today), status (processing|ready|failed), file_count, notes`.
- `project_documents`:
  `project_id, package_id, parent_document_id (zip parent), archive_path, original_filename, ext, sha256, object_key, bucket,
  size_bytes, content_type_sniffed, safety_status, rejection_reason, doc_class, sub_type, confidence numeric(4,3), title, document_number,
  revision_label, metadata jsonb, evidence jsonb, flags jsonb (duplicate, not_measurable, convert_to_dxf, conflict, low_confidence, revision_of),
  status (received|processing|proposed|confirmed|routed|failed|rejected|excluded|archive), duplicate_of_id, supersedes_id, routed_kind,
  routed_ref jsonb, confirmed_by, confirmed_at, source_text_sha256`. Index: `(project_id, doc_class)`, `(project_id, sha256)`, `(package_id)`, GIN on `metadata`.
  No unique on sha: a duplicate gets its own row with `duplicate_of_id` and the *same* `object_key` (object stored once).
- `document_classifications`: append-only proposals: `document_id, project_id, source (rules|model|user), doc_class, sub_type, confidence, evidence jsonb, metadata jsonb, is_current`.
- `addenda`: `project_id, document_id, package_id, addendum_no, issue_date, title, summary, routed_at, flagged_settlement_ids jsonb`.
- `addendum_links`: `addendum_id, project_id, target_document_id (nullable), reference_text, action (supersedes|amends), resolved bool`. (A fifth table, so links have real FKs instead of an id array.)
- `tender_class_config`: per-tenant `code, label, enabled, sort_order`. Defaults come from code; rows only override (admin can rename/disable). Thresholds are env settings, not rows.
- Also: `drawings.supersedes_id` (nullable self FK, for revision lineage; `revision_label` and `discipline_hint` already exist and are now written).

Audit (existing `audit.record`, no new actions needed): `IMPORT` (package uploaded), `CREATE` (document/addendum/drawing), `UPDATE` with payload
`{event: classify|confirm|reclassify|edit_metadata|exclude|rerun|route, from, to}`, `DOWNLOAD`. Worker classification events use the system context.

## 4. Storage

- Bucket: reuse `installtec-drawings` (a new bucket needs env, Makefile and SeaweedFS identity changes; not worth it). Key `tender/{tenant_id}/{sha256}`.
  Dedupe means the same key is written at most once per content; `put_object_streaming` returns the sha so the key is computed after hashing (hash locally first, then put).
- Drawing routing creates the `Drawing` pointing at the same object key (no copy). This bypasses `upload_drawing`'s filename-keyed key on purpose (that key can overwrite).
- A file that fails safety is kept (for audit) but never downloadable: download requires `safety_status = accepted`.

## 5. Safety layer (extends C2, `backend/app/intake/safety.py`)

Reuses `attachment_safety` primitives (`_sniff`, `_check_zip_bomb`, `_has_macro`, limits) and `AttachmentSafetyStatus`. Differences from C2:

- Allow-list `pdf, dxf, dwg, xlsx, xls, csv, docx, doc, jpg, jpeg, png, zip`. `xlsm`/`docm`/`xlsb`/`pptm` rejected by extension; macros inside zips (`vbaProject.bin`) rejected.
- DXF: text sniff (`0\nSECTION` / `AutoCAD` header markers) since C2's csv fallback would label it csv.
  DWG: magic `AC10xx`; stored, flagged `convert_to_dxf`, never parsed.
- OLE (`D0CF11E0`): a legacy `.xls`/`.doc` is allowed by extension; encrypted OOXML shows as OLE with an `.xlsx`/`.docx` extension and is rejected as encrypted.
- docx: zip with `wordprocessingml` in `[Content_Types].xml`; xlsx: `spreadsheetml`.
- Archives (`intake/archive.py`): stdlib `zipfile`, never `extractall`.
  Limits (env-configurable, defaults): entries 1,000; per-entry 100 MiB; per-file cap 60 MiB; total uncompressed 500 MiB per package; ratio 100:1; nesting depth 2 (zip in zip in zip rejected); no encrypted members (`flag_bits & 1`).
  Member names are normalised (backslashes, drive letters, `..`, absolute paths, NUL rejected as `rejected_archive`); the name is only ever stored as text, never used as a filesystem path.
  Nested zips are expanded with depth+1; entries that are directories or `__MACOSX` are skipped.
- Time limits: worker `soft_time_limit=600` for the package and a per-document budget (`intake_doc_timeout_s`, default 60) enforced with a deadline checked between stages; PDF pages read capped at 3.
- API upload caps: per file 60 MiB, per request 300 MiB, 300 files (a zip carries the rest).

## 6. Classification

Classes (code -> label; sub-types for `drawing`): `drawing` (civil_infra, architectural, structural, mep, landscape, other), `boq`, `addendum`, `specification`,
`contract`, `tender_instructions`, `tender_forms`, `clarification`, `programme`, `site_investigation`, `correspondence`, `other`.

### Stage 1 (`intake/rules.py`, pure, no GPU)

Inputs (`intake/extract.py`): filename, ext, sniffed type, first-3-page text (pypdf), page count, vector density (pdfplumber lines+rects+curves per page-1 area),
DXF text entities, xlsx sheet names + first 40 rows, docx text (zip XML, first 20k chars).
Each rule returns `(class, sub_type, weight, evidence{rule, matched, page})`; weights are 0-1.

| Rule | Class | Weight |
|---|---|---|
| ext `dxf`/`dwg` | drawing | 0.95 / 0.90 |
| xlsx header sniff: a row with >=3 of {item, description, unit/uom, qty/quantity, rate, amount} | boq | 0.90 (0.95 with all 5) |
| PDF/DOCX text: "Bill of Quantities", "Schedule of Quantities" | boq | 0.80 |
| "ADDENDUM No", "Addendum #", "Addenda" in title lines | addendum | 0.90 |
| "Conditions of Contract", "FIDIC", "Particular Conditions", "Agreement" | contract | 0.85 |
| "Instructions to Tenderers", "Instructions to Bidders", "ITT" | tender_instructions | 0.85 |
| "Form of Tender", "Bid Bond", "Performance Bond", "Appendix to Tender" | tender_forms | 0.85 |
| "Request for Information", "RFI", "Clarification No", "Response to" | clarification | 0.80 |
| "Programme", "Gantt", "Baseline schedule" (+ xlsx/mpp names) | programme | 0.70 |
| "Geotechnical", "Soil Investigation", "Borehole" | site_investigation | 0.85 |
| "Specification", "Section NN NN NN", "Part 1 General" | specification | 0.75 |
| title-block regex (drawing no + revision + scale in bottom-right region) | drawing | 0.90 |
| vector density high (>= 400 primitives per page-1) with little text | drawing | 0.65 (raises a text rule's tie) |
| filename `ADD-\d+` / `ADDENDUM` | addendum | 0.70 |
| filename `BOQ`, `BILL` | boq | 0.60 |
| filename `DWG`, `C-101 Rev B`-style, `[A-Z]{1,3}-\d{2,4}` + rev | drawing | 0.60 |
| filename `SPEC`, `CONTRACT`, `ITT`, `RFI`, `PROG`, `GEOTECH`, `LETTER` | matching class | 0.55 |
| raster PDF/image, no text | other | 0.25 (forces model with the image) |

Combine: sum-of-evidence per class with noisy-or (`1 - prod(1-w)`), capped at 0.98. Winner = highest. **Conflict** = runner-up noisy-or >= 0.5.
Sub-type for drawings from the discipline: title-block text, layer names, or drawing number prefix (`C-`, `A-`, `S-`, `M-/E-/P-`, `L-`).

**Thresholds (env):** `intake_rules_confident=0.85` (skip the model when the winner >= 0.85 and there is no conflict);
`intake_bulk_confirm_min=0.85` (bulk-confirm only proposals >= this, not conflicted, not failed, not duplicate-flagged).

### Stage 2 (`intake/classifier.py`, local vLLM, guided JSON)

- Runs only when stage 1 is below threshold or conflicted. Input: filename, first pages' text (<= 6,000 chars), title-block region text; a page-1 PNG only when there is no text layer.
- Prompt `ai-service/prompts/document_classification.j2`; schema `ai-service/schemas/document_classification.schema.json`, `additionalProperties:false` everywhere.
  Fields: `doc_class` (enum), `sub_type` (nullable enum), `confidence`, `evidence_quote`, `evidence_page`, `metadata{document_number,title,revision,date,discipline,sheet_number,scale,addendum_number,addendum_issue_date,supersedes[],sheet_names[],header_row}`.
  **No action-like property names** (avoids `action`, `status`, `approve`, `send`, `email`, `role`, `token`, `boq_line_item_id`): the same boundary test as C2 is copied and run on this schema.
- Prompt-injection boundary: system prompt says document text is content, not instructions; user prompt wraps the text in a fenced `<<<DOCUMENT` block; the model can only choose enum values, so injected text cannot cause any action (the code never reads anything but the schema fields, Pydantic drops extras).
  Tests: prompt-contract test (ai-service), schema boundary test (backend unit), and a wrapper test with a hostile document and a fake model response carrying extra `action` fields (dropped).
- `vllm.extract_json` gets a `max_tokens` parameter (default stays 512; classification asks for 700).
- Result combination: if the model class equals a stage-1 candidate its confidence is averaged with the stage-1 evidence; if not, the model wins only when its confidence >= 0.5, else stage 1's best is kept and flagged `low_confidence`. Model failure or timeout never fails the document: stage 1 result stands, flagged `model_unavailable`.
- **mock-vllm** (`ai-service/mock-vllm/main.py`): a branch for schema title `DocumentClassification` that returns deterministic keyword-driven JSON from the user text (same keyword table as stage 1 but independent, so the mock is not trivially the rules), and `Drawing/other` when only an image is attached. Also parses obvious `No.`/`Rev`/`Scale` metadata. The accuracy test imports the mock's function directly.

### Metadata (`intake/metadata.py`)

Regexes for document/drawing number (`[A-Z]{1,4}-?\d{2,5}(-\d+)?`), revision (`Rev(ision)?\.?\s*[A-Z0-9]{1,3}`), date (ISO, `dd Mon yyyy`, `dd/mm/yyyy`), scale (reuse `takeoff.scale.parse_scale_text`), sheet (`Sheet \d+ of \d+`), discipline, addendum number
(`ADDENDUM\s*(No\.?|#)?\s*\d+`), addendum issue date, supersede references ("supersedes / replaces / amends / in lieu of  <docno> [Rev X]"; lines beginning "Drawing C-101 Rev A is replaced by Rev B"), BOQ sheet names and header row.
Values found by regex are proposals; editing is manual. Everything is stored in `metadata` JSON and copied to `document_number`, `title`, `revision_label`.

## 7. Duplicates and revisions

- Same sha256 in the project: `duplicate_of_id` = earliest row, same `object_key`, flag `duplicate`, status `proposed` but excluded from bulk confirm; confirming a duplicate marks it `routed` with `routed_kind='duplicate'` and does not route again.
- Same document/drawing number, different sha and revision: flag `revision_of=<id>`. On routing, the new row's `supersedes_id` points at the latest earlier revision (revision order: numeric, else alphabetic, else received time).

## 8. Routing on confirm (`services/tender_intake.py::route_document`)

- **drawing**: DXF/vector PDF -> `takeoff_service.create_drawing_from_stored(...)` (new; reuses the object, sets `revision_label`, `discipline_hint`, `supersedes_id`, dedupes on `(project, sha)`), then `trigger_ingest` (which dispatches `index_sheets` with actor roles). Raster/scanned PDF or image, or DWG: `routed` with flag `not_measurable` (DWG also `convert_to_dxf`); no drawing created for DWG, a raster PDF gets a Drawing row so it is visible but flagged.
- **boq** (xlsx/xls/csv): `routed_kind='boq_wizard'`, `routed_ref={sheet_name, header_row, suggested_mapping}`. Endpoint `GET /tender-documents/{id}/boq-prefill`. The wizard accepts `?document=<id>`: fetches the file via download, prefills the mapping and sheet, user still runs dry run then commit. Backend change: `BoqImportColumnMapping.sheet_name` (optional, default = active sheet), used by the parser and recorded in `BoqImportBatch.sheet_name`. Retention of the original workbook is unchanged (commit already stores it). The document shows "imported" when a `BoqImportBatch` with the same sha exists.
- **addendum**: create `addenda` row + `addendum_links` from extracted supersede/amend references; resolve each reference against existing documents/drawings by document number (+revision); mark resolved. Superseded documents get their replacement linked via `supersedes_id` (the old row stays readable). Routing order inside one confirm batch is drawings, boq, others, then addenda, so links resolve inside the same pack.
  Then flag settlements: every `BidSettlement` of the project with status draft or submitted gets its id added to `addenda.flagged_settlement_ids`, and the settlement page shows "Addendum N changed the tender documents after this settlement was built" (draft: prompt to *Refresh quantities*; submitted: prompt for re-review). Cleared for a draft once `quantities_refreshed_at` is after the addendum's `routed_at`. Existing submit-time quantity check is unchanged and remains the hard stop.
- **contract, specification, tender_instructions, tender_forms, clarification, programme, site_investigation, correspondence, other**: `routed_kind='register'`. The register endpoint lists/filter/search/download. Contract documents are kept in the register with `doc_class='contract'` where Module E can later read them; nothing is written into Module E tables (no new workflow, per brief).

## 9. API (`/api/v1`, `routes/tender_intake.py`)

- `POST /projects/{id}/tender-packages` (multipart `files[]`, optional `label`, `transmittal_ref`, `received_date`) -> 202 `{package_id}`.
- `GET /projects/{id}/tender-packages`, `GET /tender-packages/{id}`.
- `GET /projects/{id}/tender-documents?package_id&doc_class&status&q&flag&limit&offset` -> `Page` (server-side paging for 300+ files).
- `GET /tender-documents/{id}` (with classification history), `GET /tender-documents/{id}/download` (302 presigned, audited), `GET /tender-documents/{id}/evidence` (snippet/page text).
- `POST /tender-documents/{id}:confirm`, `:reclassify {doc_class, sub_type}`, `:edit {metadata}`, `:exclude`, `:rerun`; `POST /projects/{id}/tender-documents:bulk-confirm {package_id?, document_ids?, min_confidence?}`.
- `GET /projects/{id}/addenda` (with links and flagged settlements), `GET /projects/{id}/document-register`.
- `GET/PATCH /tender-classes` (MD).

## 10. UI (Figma design system components only)

- Project detail page has no tabs today; add `TabBar` (`pattern='buttons'`) to `ProjectDetailPage`: "Overview" (existing content) and "Tender documents". The new tab holds a `DropZone` (new shared component: multi-file, zip, keyboard-accessible, progress via XHR-free sequential chunks = per-file `fetch` batches of 20), a package list and the review table.
- Review table: AG Grid (already themed, virtualised; 300+ rows), columns: file, proposed class, sub-type, confidence badge, number/title/revision (editable cells), evidence (click opens a modal with the snippet and page), flags, status, row actions. Server-side paging is used for the list query (limit 200), grid virtualises within the page. Toolbar: filter by class/status/flag, bulk-confirm high-confidence, confirm selected, change class (select), exclude, re-run. Reject/exclude asks for a reason in `TextPromptModal`.
- Addenda register and document register are two more sections of the tab (simple tables).
- Settlement page: banner from `/projects/{id}/addenda`.
- BOQ wizard: reads `?document=`.
- Sidebar: unchanged (tab lives under the project overview).

## 11. Worker

`app/workers/tasks/tender_intake.py`: `process_tender_package(package_id, tenant_id, actor_user_id, actor_roles)` on queue `ingest` (least invasive: no new compose service; the worker is `-Q ingest,embed`), `soft_time_limit=900`; `rerun_document`. Follows the claim-first rule: each document is processed in its own committed unit so a failure is recorded on that document (`failed` + reason) via an independent session and never rolls back others. Tasks module added to `celery_app` `include` and routes. `.apply_async(countdown=3)` so the row is committed before the worker looks (the request transaction commits at dependency exit).

## 12. Tests

- **Unit:** every rule (table-driven), metadata regexes, archive safety (traversal, bomb, ratio, nesting 3, encrypted member, macro, symlink-like names, size caps), safety allow-list, supersede/revision ordering, addendum reference parsing, boundary tests (schema, prompt contract), classifier wrapper with hostile text.
- **Integration/API:** RLS isolation per table (tenant + project scoped, non-member estimator), role tests (estimator upload ok, non-member denied, estimator confirm denied, lead confirm ok), audit events, duplicate linking, routing of each class, addendum supersede + settlement flag, worker body end to end on the fixture pack with `get/put_object` patched.
- **Fixture pack** (`backend/tests/fixtures/tender_pack.py`, generated in code, deterministic): DXF drawings (ezdxf + title-block text), vector PDFs, a scanned-style raster PDF (image only), BOQ xlsx, addendum PDF (supersedes C-101 Rev A, changes BOQ quantities), spec, contract, ITT, a zip with some of these, a duplicate, an `.xlsm`, a zip bomb. Ground-truth labels alongside for accuracy runs.
- **Playwright real-backend** (`tender-intake.spec.ts`): drop the pack; see proposals; bulk-confirm; drawings reach `ready`; BOQ wizard opens pre-filled; addendum creates a new drawing revision and flags a draft settlement.
- **Accuracy** (below), recorded here after the first full run. Real-model accuracy stays on the GPU checklist.
- Final: `make test-all`, `npm run build && npm run test && npm run lint`, `npm run e2e:real-backend --workers=1` once, MFA left off. Report `docs/tender-intake-report.md`.

## 13. Build order and subagents

1. Main session: migration 0030, models, schemas, safety/archive, extract, rules, metadata, classifier + prompt/schema/mock, service, routes, worker, tests (security-sensitive files are main-only per finish-brief A5).
2. Subagent A (worktree `agent/intake-fixtures`, Sonnet): allow-list `backend/tests/fixtures/tender_pack.py`, `backend/tests/unit/test_tender_pack_fixture.py`. Done = the generator returns the labelled files listed in section 12; unit test proves each is well-formed with the libs already installed.
3. Subagent B (worktree `agent/intake-ui`, Sonnet), after the API contract is committed: allow-list `frontend/src/features/tenderIntake/**`, `frontend/src/components/DropZone.tsx`, the new tab component, and the small `ProjectDetailPage.tsx` / `BoqImportWizardPage.tsx` / `SettlementPage.tsx` / `types/api.ts` edits. Done = `tsc -b`, oxlint and vitest pass.
4. The main session verifies each branch (real commits, full diff, allow-list, re-run checks) before merging into `feat/tender-intake`, and records that in the log. Stack-dependent runs are main-session, one at a time.

## 14. Defaults I picked (and would revisit)

- Reuse the drawings bucket with sha keys instead of a new bucket.
- `xls`/`doc` legacy files are accepted (OLE) and stored, classified from filename only; `.docx` is text-scanned via zip XML (no new dependency); `dwg` stored and flagged.
- Class admin: rename/enable/disable only; thresholds in env config.
- BOQ "new revisions from addenda" are lineage on `project_documents` only; `boq_line_items` has no revision column and `boq_revisions` is not written by anything today, so no BOQ items change until the user runs the wizard.
- Confirm is blocked for a `failed`/`rejected` document; `rerun` is allowed for `proposed|failed`.
- Timezone for `received_date`: server date.

## 15. Accuracy record

(filled in after the first full run: rules only, rules + mock model)
