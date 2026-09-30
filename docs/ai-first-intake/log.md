# AI-first intake build log (resume file)

Brief: pasted by the owner (project page + AI-first document sorting); rules: docs/finish-brief.md section A.
Branch: feat/ai-first-intake (from master after feat/ai-provider). When resuming, read this and continue from the first unchecked step.

## Design decisions (main session)
- AI reads every file first. Rules run too, but only as *hints* in the prompt and as the fallback (label "classified by rules").
- `sub_type` now holds the fine discipline (roads_civil, stormwater, sewer, water_supply, irrigation, electrical_lighting, telecom, landscape, architectural, structural, mep; legacy civil_infra/other still accepted). drawing_type, unit_type (villa type), sheet, scale, supersedes/amends live in `metadata`.
- Threshold stored on `tenant_ai_settings.intake_auto_accept_min` (default 0.850), changed by managing_director only, audited.
- Auto-accept routing runs in the worker under the system context (RLS: addenda are lead_estimator+ writes), audit payload says `decided_by: ai`.
- Drawings get `archived_at`; reclassifying a routed drawing archives it (measurements stay attached to the archived drawing) and every takeoff/verification reader excludes archived drawings. Re-classifying back restores it.
- "Batching": documents are prepared (extract + AI call) concurrently in bounded groups, then persisted one by one. Hard AI failures (not configured / not allowed / budget) trip a circuit breaker for the rest of the run, so the rules fallback is used without hammering the gateway.
- Cache by sha256: identical content in a project copies the original's classification (no call); the gateway's own cache covers re-runs on external providers.

## Steps
- [ ] 1 migration 0037 + models + constants
- [ ] 2 schema/prompt v2, classifier, mock fixtures
- [ ] 3 processing pipeline (AI first, fallback, auto-accept)
- [ ] 4 service: settings, reclassify anywhere + unroute, bulk reclassify, tree/summary endpoints
- [ ] 5 drawing archive + reader filters
- [ ] 6 backend tests (unit, integration, api), each suite separately
- [ ] 7 frontend: one project page, tree, needs-your-check, admin setting
- [ ] 8 demo pack + real-backend walkthrough; update old specs/screenshots
- [ ] 9 report, merge to master, MFA left off
