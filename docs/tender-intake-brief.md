# Est Build: Approvals Inbox Fix + Tender Document Intake Brief

Same working rules as `docs/finish-brief.md` section A: the main session merges, subagents work in worktrees with file allow-lists, the main session verifies everything, stack-dependent tests run one at a time with `--workers=1`, and nobody pushes. Keep `docs/tender-intake/log.md` current and resume from it.

---

## Part 1: approvals you can actually act on (branch `fix/approvals-inbox`)

**Bug:** the "Approvals waiting for me" tile on `HomeDashboardPage` renders plain text (entity type, amount, step). There's no link, no project, and no way to approve or reject. Also check whether `cost_rate_change` approvals have any UI to decide them at all.

1. **Each row links to where the decision is made**, and shows:
   - the project code and name;
   - a readable type ("Bid settlement v2", "Cost rate change"), not `bid_settlement`;
   - the amount, and margin-on-sell for settlements (3 dp);
   - who submitted it and when;
   - the tier/role it's waiting on.
2. **A new `/approvals` page**, linked from the tile ("View all") and the sidebar: every approval pending for me, plus the ones I've decided recently. Approve and reject happen on the **entity's own page**, where the approver sees the full context: the settlement cockpit, or a new cost-rate-change detail view if none exists. No blind approve buttons in a list.
3. **The existing rules stay exactly as they are.** SoD (the submitter can't decide), step-up (or the dev bypass, with its audit flag), and server-side role checks. Reject requires a reason in a modal.
4. **Tests:**
   - a real-backend spec: lead1 submits → md1's dashboard tile shows it → click → settlement page → approve → the tile empties;
   - the submitter sees it as "Awaiting a different approver" with no actions;
   - `cost_rate_change` is covered the same way;
   - lowest allowed role and a denied role for any new endpoint.

---

## Part 2: tender document intake with classification (plan first, then build)

**Goal:** after creating a project, the user drops everything the client sent (loose files or a .zip) into one place. The system identifies each document, extracts its key metadata, proposes where it goes, and after the user confirms, routes each file into the right pipeline.

### 2.0 Plan first
Write `docs/tender-intake-plan.md`: the data model, the classes, the rules, the model prompt and schema, the routing, the UI, and every default you pick. Commit it, **then build without waiting**, unless one of the stop conditions in finish-brief section A applies. The branch is `feat/tender-intake`.

### 2.1 Upload
- A "Tender documents" tab on the project, with a drop zone for many files or a .zip. Role: estimator+ can upload; confirming the classification is lead_estimator+.
- **Re-use the C2 attachment safety layer** and extend it for archives:
  - content sniffing and an allow-list: pdf, dxf, dwg (stored and flagged "convert to DXF/PDF", not parsed), xlsx, xls, csv, docx, doc, jpg, png, zip;
  - zip-bomb and ratio limits, a nesting depth limit (2), and per-file and total size caps;
  - reject encrypted files and macros (`xlsm`, `docm`); path-traversal-safe extraction;
  - all of it runs in a worker with time limits.
- Store every original in S3, keyed by sha256. Duplicate files are detected and linked, not stored twice.

### 2.2 Classification: deterministic first, then the model, and always a proposal
- **Classes** (configurable in admin, but these are the defaults):
  - Drawing, with sub-types by discipline (civil/infra, architectural, structural, MEP, landscape);
  - BOQ;
  - Addendum;
  - Specification;
  - Contract / Conditions (e.g. FIDIC, particular conditions);
  - Tender instructions (ITT / instructions to tenderers);
  - Tender forms and bonds;
  - Clarification / RFI response;
  - Programme / schedule;
  - Site investigation / geotechnical report;
  - Correspondence;
  - Other.
- **Stage 1, rules, which must work with no GPU:**
  - the file type (DXF means drawing);
  - xlsx header sniffing (item, description, unit, qty and rate columns mean BOQ);
  - PDF text keywords and title-block regexes (drawing number, revision, scale, "ADDENDUM No.", "Bill of Quantities", "Conditions of Contract", "Instructions to Tenderers");
  - filename patterns (`ADD-01`, `BOQ`, `DWG`, `SPEC`, `C-101 Rev B`);
  - vector-PDF page geometry density, which suggests a drawing.

  The result is a class, a confidence and the evidence (which rule fired, with the matched text).
- **Stage 2, the local vLLM**, only for files below the confidence threshold or with conflicting rules:
  - guided JSON with a strict schema (class, sub-type, confidence, extracted metadata, evidence quote with page); **no action fields**;
  - input is the first pages' text plus the title-block region; images only when there's no text layer;
  - add a prompt-injection boundary test, as in C2.

  The mock model must return plausible deterministic output so the flow is testable.
- **Metadata to extract:**
  - document or drawing number, title, revision, date, discipline, sheet number, scale;
  - for addenda: the addendum number, its issue date, and the documents or drawings it **supersedes or amends**;
  - for BOQs: the sheet names and the detected header row.
- **Nothing is routed automatically.** Every classification is a proposal until a lead_estimator+ confirms it. Bulk-confirm high-confidence items, and review the rest one by one.

### 2.3 Review screen
- A table of every file: the proposed class and sub-type, confidence, extracted metadata (editable), evidence (click to see the page or snippet), duplicate and revision flags, and status (proposed, confirmed, routed, failed).
- **Actions:** confirm, bulk-confirm, change the class, edit the metadata, exclude, and re-run classification. All of them audited.
- Use the Figma design system components. The table must stay usable with 300+ files, since real tender packs are large.

### 2.4 Routing after confirmation
- **Drawing (DXF or vector PDF)** goes into the existing drawing ingestion and extraction pipeline, with the extracted number, revision and discipline attached. Scanned or raster drawings are flagged as not measurable.
- **BOQ** goes into the existing BOQ import wizard, pre-filled with the detected sheet and header row. The user still confirms the column mapping (dry run, then commit), and the original workbook is retained, as D2/D3 already do.
- **Addendum:**
  - recorded in an **addenda register** (number, date, what it affects);
  - superseded documents get a new revision linked to the old one (the old one stays readable);
  - if the addendum brings a new BOQ or drawings, those are routed as above as new revisions;
  - flag any settlement in draft or submitted status for this project, so that "refresh quantities" and a re-review are prompted. Re-use the existing quantity check at submit.
- **Contract, Specification, Tender instructions, Forms, Clarifications, Programme, SI report, Correspondence** go into a **project document register**: stored, versioned, searchable by metadata, and downloadable. Contract documents are linked where Module E expects them later. Don't build new workflows for these.

### 2.5 Data model (migrations, with RLS FORCEd on every table, and isolation tests)
- `tender_packages` (one per upload batch or transmittal, with a received date);
- `project_documents`, with sha256, class, sub-type, metadata JSON, status and revision lineage (`supersedes_id`);
- `document_classifications`, keeping every proposal with its source (rules or model), confidence and evidence;
- `addenda`, with links to the affected documents.

All state changes are audited.

### 2.6 Tests and verification
- Build a **synthetic tender pack** as a fixture: DXF drawings, vector-PDF drawings, a scanned-style PDF, a BOQ xlsx, an addendum PDF that supersedes one drawing and changes BOQ quantities, a spec PDF, a contract PDF, an ITT, a zip containing some of these, a duplicate file, a .xlsm and a zip bomb.
- **Unit tests:** every rule; metadata regexes; archive safety; addendum supersede logic.
- **Integration and API tests:** RLS isolation; role tests (lowest allowed and denied) for upload, confirm and route; audit events.
- **A real-backend Playwright spec:**
  1. drop the pack;
  2. see the proposals;
  3. bulk-confirm;
  4. drawings reach `ready`;
  5. the BOQ wizard opens pre-filled;
  6. the addendum creates a new drawing revision and flags a draft settlement.
- **Record classification accuracy** on the synthetic pack, both rules-only and rules plus mock model, in the plan doc. The real-model accuracy run stays on the GPU checklist.
- At the end: `make test-all`, the frontend checks, and `npm run e2e:real-backend --workers=1` once, clean. Write `docs/tender-intake-report.md`, merge, leave MFA off, and stop.
