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

## Part 2: tender intake (`feat/tender-intake`)
- [x] Plan committed (`docs/tender-intake-plan.md`).
- [x] Subagent A (`agent/intake-fixtures`, synthetic pack) verified: commit d5418b8 exists, only the 2 allow-listed files, merged. Main session fixed one thing it got wrong (xlsx `modified` timestamp is stamped inside `save()`, so the pack was not deterministic) and ran its tests.
- [x] Migration 0030, models, constants, settings, archive/safety, extract, rules, metadata, classifier, prompt+schema, mock-vllm branch. 97 unit tests pass.
- [ ] service, routes, worker, ai-service prompt contract test, integration/API tests (RLS, roles, audit, routing)
- [ ] frontend (subagent B), BOQ wizard prefill, settlement banner
- [ ] Playwright real-backend spec, full regression, report, merge
