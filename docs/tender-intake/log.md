# Tender intake run log

Resume from the first unfinished step. Brief: `docs/tender-intake-brief.md`.

## Part 1: approvals inbox (`fix/approvals-inbox`) -- DONE
- Backend: `GET /approvals/inbox` (lead_estimator+; estimator gets 403) returns `pending`
  (current step is one of my roles; my own submissions flagged `awaiting_other`) and `recent`
  (decided by me, last 30 days). `pending-for-me` and `GET /approvals/{id}` now carry
  project code/name, submitter, waiting role, settlement version and 3dp margin.
  `decide()` and every SoD / step-up / role rule are untouched.
- Found and fixed: a rebuilt settlement version leaves its old approval request `pending`
  forever (orphan). Those linked to the *current* settlement for every approver. Inbox and tile
  now hide bid_submission requests whose settlement is not the current submitted one.
- Frontend: tile rows are links (project, "Bid settlement v3" / "Cost rate change", amount,
  margin, submitter, when, waiting role, "View all"); `/approvals` page + sidebar link;
  `/approvals/:id` decision page (approve, reject with required reason modal, step-up handling)
  for non-settlement approvals. Settlements are decided on the settlement cockpit as before.
- cost_rate_change finding: nothing in the app creates these requests (recording a rate applies
  immediately) and there was no UI. The detail page now decides them; tests create them through
  the generic `POST /approvals`.
- Deviation from the brief: settlements are submitted by bd_director/managing_director (lead1 cannot),
  so the spec uses bd1 submits -> md1 approves.
- Known, left alone (approvals.py is security-sensitive, rules must stay): the generic
  `POST /approvals/{id}/decide` still accepts a bid_submission request without syncing the
  settlement status; the UI never calls it that way.
- Verified: api + integration approvals tests, vitest, `tsc -b`, real-backend
  `approvals-inbox.spec.ts` (settlement, cost rate, axe) with MFA off and on, plus home-dashboard
  and settlement specs.

## Part 2: tender intake (`feat/tender-intake`) -- DONE, see docs/tender-intake-report.md
- [x] Plan, migration 0030, safety/archive, rules, metadata, classifier + prompt/schema/mock, service, routes, worker, BOQ `sheet_name`, content endpoint.
- [x] Subagent A (fixtures, d5418b8) and B (UI, 8ab7986) verified under rule A7 and merged; main session added admin tab, resumable upload, spec, fixes.
- [x] make test-all: 473 unit, 230 integration, 62 API. Frontend build/vitest 78/lint/mocked e2e green.
- [x] Real-backend e2e: intake specs pass (flow, admin classes, 338-file pack). Two full runs (87/88, then 75/88 with connection resets) and all failures re-run green; no single clean 88/88 (third run killed by low memory, not restarted).
- [x] Found and fixed: dev-set-mfa.sh mangled ONNX_MODEL_DIR under Git Bash.
- [x] MFA off.
