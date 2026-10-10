# BOQ agent: API contract for the UI

Base path `/api/v1`. All JSON. Decimal fields are numbers. IDs are UUIDs. Errors use the app's problem+json (`status`, `title`, `detail`).
Roles: **lead_estimator, procurement_head, bd_director, managing_director** can start runs, confirm, pause/resume/cancel, chat and confirm lines.
**estimator** (a member of the project) can only read runs, steps, proposals, agent lines and chat messages. Anyone not on the project gets 403/404.

## Runs

| Method and path | Who | What |
|---|---|---|
| `POST /projects/{pid}/agent/runs` body `AgentRunCreate` | lead+ | Creates a run. `202` + `AgentRunDetail`. `status` is `awaiting_confirm` when the AI provider is external (nothing has been spent: show `estimate` and ask), otherwise `queued`. `409` if a run is already active for the project, or the current settlement is not a draft (send `create_draft: true` to start a new draft version). `422` for an unknown section or a project without BOQ lines. |
| `POST /agent/runs/{id}/confirm` | lead+ | Accepts the cost estimate. `202`. Only valid in `awaiting_confirm` (`409` otherwise). |
| `POST /agent/runs/{id}/pause` · `/resume` · `/cancel` | lead+ | `409` if the status does not allow it. A running section stops after its current step. |
| `GET /projects/{pid}/agent/runs` | estimator+ | `AgentRunOut[]`, newest first (20). |
| `GET /agent/runs/{id}` | estimator+ | `AgentRunDetail` (the run + `sections[]`). Poll every 2-3 s while `status` is `queued|planning|running|awaiting_confirm`, every 15 s otherwise, stop when terminal (`done|stopped_limit|failed|cancelled|blocked`). |
| `GET /agent/runs/{id}/steps?after_seq=&section_id=&limit=` | estimator+ | `AgentStepOut[]` ascending by `seq`. Poll with `after_seq` = the last `seq` you have. |

`AgentRunCreate`: `{ sections?: string[] (section ids or item numbers), line_ids?: uuid[], notes?: {sectionId: string}, limits?: {max_steps, max_page_views, max_usd}, create_draft?: boolean }`. All optional.

`AgentRunOut`: `id, project_id, kind ('run'), settlement_id, status, scope, limits {max_steps, max_page_views, max_usd}, estimate {provider, model, external, sections, steps, page_views, usd, usd_uncapped, usd_cap, unverified_price, note}, plan {summary, sections[{section_id, folders[], queries[], why}]}, summary, provider, steps_total, page_views, ai_calls, cost_usd, error, started_by, confirmed_by, confirmed_at, started_at, finished_at, created_at`.
`summary` (when finished): `{ applied: {applied, skipped_person_set?, ...}, sections: {status: count}, files_read, files_in_pack, files_read_ratio, proposals, seconds, lines_without_proposal }`.

`AgentSectionOut`: `id, section_item_id, label, seq, status ('pending'|'reading'|'done'|'stopped_limit'|'failed'|'cancelled'), line_count, steps, plan, summary, coverage, stop_reason ('steps'|'cost'|'budget'|'time'), error, started_at, finished_at`.
`coverage`: `{ files_read: [{file_id, path, pages[]}], found_not_read: [{file_id, path, why_found, why_not_read}], lines_total, lines_proposed, lines_without_proposal: uuid[], lines_cost_source_only }`.

`AgentStepOut`: `id, run_id, section_id, seq, tool, args, note, ok, result_summary, file_refs [{document_id, filename, page}], tokens_in, tokens_out, cost_usd, injection, created_at`. `injection: true` means the tool's text looked like instructions (the agent was warned; show a small badge).
Tool names: `boq_outline boq_lines list_folder search_files file_info read_text read_sheet view_page read_title_block get_measurements verify_lines cost_candidates propose_line finish_section` (+ chat: `run_status explain_line rerun_section`; an invalid step is stored as `invalid`).

**Opening a file at a page:** `file_refs[].document_id` is a tender document. The file bytes are at `GET /tender-documents/{document_id}/download` (same-origin); for a PDF open `.../download#page=N` in the existing document viewer used by the intake tree, or a new tab.

## Agent lines on the settlement

| Method and path | Who | What |
|---|---|---|
| `GET /bid-settlements/{sid}/agent-lines` | estimator+ | `AgentLineOut[]`: `{line_id, boq_line_item_id, cost_source ('agent_candidate'|'agent_estimate'), direct_unit_cost, source_currency, agent_proposal_id, agent_confirmed_by, agent_confirmed_at, proposal}` with `proposal` = `AgentProposalOut` below. |
| `GET /bid-settlements/{sid}/agent-summary` | estimator+ | `{agent_lines, unconfirmed}` for the "N agent lines need confirmation before submit" banner. |
| `POST /bid-settlements/{sid}/lines/{line_id}/agent-confirm` body `{proposal_id}` | lead+ | Confirms one line. Send the `agent_proposal_id` of the proposal the drawer showed. `409` if the line moved on ("reload and look again") or the settlement is not a draft. `403` for an estimator. |
| `POST /bid-settlements/{sid}/agent-confirm-bulk` | lead+ | Confirms every unconfirmed `agent_candidate` line with confidence >= 0.85 and no blocking flag. `{confirmed, skipped: {estimate, blocked_or_low_confidence}}`. Estimates are never bulk-confirmed. |
| `PATCH /bid-settlements/{sid}/lines/{line_id}` (existing) | estimator+ | **Replace**: a person setting the cost (manual / quotation / library) takes the line over; the agent marks and the proposal are cleared. |
| `GET /agent/proposals/{id}` | estimator+ | One `AgentProposalOut`. |

`AgentProposalOut`: `id, run_id, boq_line_item_id, kind ('candidate'|'estimate'), candidate_ref ('q:..'|'c:..'|'h:..'), rate, currency, uom, as_of, method (estimates), evidence [{file_id, path, page, quote, kind} | {kind:'cost_source', ref, label, type}], qty_check {boq_quantity, measured, unit, delta_pct, class}, flags[], confidence, rationale, status ('proposed'|'applied'|'superseded'|'rejected_by_user'), applied_at`.
Flags worth a visible chip: `agent_estimate`, `no_document_check`, `stale_rate`, `quote_exclusions`, `vendor_not_eligible`, `large_deviation`, `needs_fx`, `quantity_variance`, `unit_alias`.
`BidSettlementLineItemOut` (existing endpoints) now also carries `agent_proposal_id, agent_confirmed_by, agent_confirmed_at`; `cost_source` can be `agent_candidate` or `agent_estimate`. `POST .../submit` returns `409` with `unconfirmed_agent_line_ids` when any agent line is unconfirmed.

## Chat

| Method and path | Who | What |
|---|---|---|
| `POST /projects/{pid}/agent/chat` body `{message, conversation_id?}` | lead+ | `202` `{conversation_id, message, run_id}`. `409` while the last message is still being answered. |
| `GET /agent/conversations/{cid}/messages?after=<created_at>` | estimator+ | `ChatMessageOut[]` ascending. Poll every 2 s while the latest message is the user's; stop once an `assistant` message arrives. |
| `GET /projects/{pid}/agent/conversations` | estimator+ | `ConversationOut[]` (`id, title, created_at`), newest first. |
| `GET /agent/runs/{run_id}/steps` | estimator+ | The chat turn's own steps (the `run_id` in `ChatPostOut` / `ChatMessageOut.run_id`). |

A chat turn is capped at 15 steps and 0.50 USD and ends with a message either way. Chat can propose lines (they land in the draft settlement, unconfirmed) and ask for a section re-run; it cannot submit, approve or change percentages, FX rates or quantities.

## Intake settings

`GET /tender-intake/settings` and `PUT /admin/intake-settings` (managing_director / the class-admin roles) now carry `ai_classify: boolean` (default `false`). Off: upload is a fast index and nothing is sent to a model; on: every uploaded file is classified by the AI (slow, costs money, needs the cost confirmation as before). The Admin > AI screen should show it as a switch with that explanation.

## Manifest-based document tree

The existing tree endpoints (`/projects/{pid}/tender-documents/tree` and `/items`) are unchanged. With `ai_classify` off, documents carry the rules' classification (`classified_by: 'rules'`) and most are not routed; the tree already groups by folder and class hint. "Read by the agent" is not an API field yet: use the latest run's `sections[].coverage.files_read[].file_id` (union over sections) to mark files.

## UI requirements (from the brief)

- Project page: a **Run estimation agent** action (shows the estimate and a confirm when `status = awaiting_confirm`) and an **Agent** tab: progress per section (pending / reading / done / stopped at limit), cost so far, Pause / Resume / Cancel; the **trace** (plan, then each step: tool, file, pages, the agent's note, links that open the file at the page); the coverage report per section; the chat panel.
- Settlement page: agent lines visibly marked (source badge, confidence, flags), an evidence drawer per line (files, pages, measurements, verification class, rationale), Confirm / Bulk confirm / Replace, and a banner "N agent lines need confirmation before submit".
- Design system, IBM Plex, lucide icons, axe clean. Only lead+ see the action buttons; estimators see the same data read-only.
