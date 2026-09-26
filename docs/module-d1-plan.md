# Module D1 plan: Bid Settlement & Margin Simulation

Covers SRS §4 Module D bullet 1 ("Bid Settlement & Margin Simulation"). Built
under `docs/preconstruction-build-brief.md`'s Phase 1, which supersedes the
original per-module "wait for OK" checkpoint — this plan is committed, then
built straight away. D2 (Client BOQ Export, Win/Loss Capture) is a separate
plan.

**Revision note (this version):** rewritten per the brief's Phase 1
corrections vs. the original proposal — rates are now authoritative (no
rounding-residual/largest-line absorption), segregation of duties is
enforced generically in the approval engine, the settlement status
lifecycle is explicit, submit checks quantities against the live BOQ, and
boundary tests are enumerated. §4/§5 are fully rewritten; everything else
carries over from the original proposal.

## 1. Scope recap

- One settlement consolidates a **whole project** (all its procurement
  packages plus any self-performed/manually-costed BOQ items) into a single
  traceable settled bid, versioned like `Quotation` (a new version never
  mutates an earlier one; only one `is_current=true` per project).
- "Margin" is implemented as **markup on cost** (`markup_pct`, applied on
  top of landed cost — direct cost + plant allowance + site overhead +
  volatility allowance). This is the field the SRS itself names
  ("real-time simulation across **markups** and volatility allowances").
  **Margin-on-sell is always shown too**, computed from the actual
  authoritative sell total (§4) — never a second stored input.
- Four adjustable percentage types, each resolvable at **project default →
  per-trade override → per-line override** (line wins, then trade, then
  project default): `plant_pct`, `overhead_pct`, `volatility_pct` (the
  SRS's "volatility allowance", applied per-trade as required), `markup_pct`.
- Every settlement line's cost is one of: an accepted procurement quote
  line, a bi-temporal Master Cost Library rate (as-of a date), or a manual
  entry (who, why). Currency mismatches block submission until a reviewer
  records an FX rate.
- Simulation is stateless (no DB writes) so it's cheap to call repeatedly;
  named scenarios can optionally be saved for side-by-side comparison.
- Explicit status lifecycle: `draft → submitted → approved | rejected →
  won | lost` (§5a). Submitting snapshots everything (immutable from then
  on) and raises an approval request through a **new, settlement-specific**
  policy. The submitter can never approve their own settlement (§5b).

## 2. Data model

### 2a. Two additions to the existing approvals engine (Module A)

**Margin-based routing.** The generic engine (`app/services/approvals.py`)
only routes tiers on a single `amount` threshold today. The agreed rule —
*"managing_director if sell_total > AED 2,000,000 **or** margin-on-sell <
8%, otherwise bd_director"* — is an OR across two independent signals, so
`ApprovalPolicyTier` gets one new nullable column:

```
approval_policy_tiers.max_margin_pct  NUMERIC(5,2) NULL
```

A tier matches if its amount bracket matches **or** (`max_margin_pct` is
set and the caller's `margin_pct < max_margin_pct`, strictly-less-than —
see the boundary tests in §6). `route_tiers()` gains an optional
`margin_pct: float | None = None` parameter (default `None` preserves
every existing caller's behaviour exactly — `cost_rate_change`'s tiers all
have `max_margin_pct=NULL`, so the OR clause is always false for them).
`ApprovalRequestCreate` gains an optional `margin_pct` field, passed
straight through.

Seeded policy (new migration data, `app/cli.py`-style seed,
entity_type=`bid_settlement`, mode=`highest_tier_only`):

| seq | min_amount | max_amount | max_margin_pct | required_role |
|---|---|---|---|---|
| 1 | 0 | 2,000,000.00 | — | `bd_director` |
| 2 | 2,000,000.01 | — | 8 | `managing_director` |

`min_amount=2,000,000.01` on tier 2, not `2,000,000.00`, is deliberate:
`route_tiers`'s bracket check is `min <= amount <= max` (inclusive both
ends), and the brief's rule is a **strict** `> 2,000,000` — at exactly
2,000,000.00 only tier 1's bracket matches (unless the margin clause also
fires), at 2,000,000.01 only tier 2's does. See §6 for the boundary tests
this is written to satisfy.

**Segregation of duties (pre-existing gap, fixed generically).** Nothing in
`approvals.decide()` today stops the person who created an
`ApprovalRequest` from also deciding its own step — a real gap, and one
that predates this module (it already affects `cost_rate_change`, unused in
production so far but still a live gap in shipped code). Fixed once, in
`decide()` itself, so every entity type using the generic engine is
covered:

```python
if request.requested_by == ctx.user_id:
    raise ForbiddenError("The requester cannot decide their own approval request")
```

Logged in `docs/build-log.md` as a pre-existing bug found and fixed, not
new-module scope creep.

MFA step-up on the decision itself is inherited for free — `decide()`
already requires `acr=silver`+ on every step regardless of entity type.

### 2b. New tables

```
bid_settlements                 -- one row per version, per project
  id, tenant_id, project_id
  version_no int, is_current bool          -- partial unique (project_id) WHERE is_current, same pattern as quotations
  status              draft | submitted | approved | rejected | won | lost   -- see §5a
  currency            char(3)
  default_plant_pct, default_overhead_pct, default_volatility_pct, default_markup_pct   numeric(6,4), default 0
  -- populated only at submit (snapshot); NULL on a draft
  direct_cost_total, plant_total, overhead_total, volatility_total, markup_total   money, nullable
  tender_total        money, nullable   -- authoritative: Σ line_items.line_amount (§4) -- this, not a theoretical total, is what's approved/exported/charged
  rounding_difference money, nullable   -- tender_total minus the exact unrounded model total; stored for audit, never corrected away
  margin_on_sell_pct  numeric(6,3), nullable
  approval_request_id uuid, nullable FK -> approval_requests
  quantities_refreshed_at   timestamptz, nullable   -- last time §5c's refresh action ran on this draft
  submitted_at, submitted_by
  decided_at, decided_by                             -- §5a: who/when approved or rejected (mirrors approval_requests but kept local for a fast status read)
  outcome             won | lost, nullable                      -- D2, table exists now so D1's schema is final
  outcome_our_price, outcome_winning_price   money, nullable
  outcome_competitor_names   text[], nullable
  outcome_reason_codes       text[], nullable
  outcome_recorded_by, outcome_recorded_at, outcome_note   nullable
  notes  text, nullable

bid_settlement_trade_overrides  -- sparse: a row only where a trade needs an override
  id, tenant_id, settlement_id FK, trade_node_id FK
  plant_pct, overhead_pct, volatility_pct, markup_pct   numeric(6,4), each nullable (NULL = inherit project default)
  unique(settlement_id, trade_node_id)

bid_settlement_line_items       -- one per BoqLineItem included in the settlement
  id, tenant_id, settlement_id FK, boq_line_item_id FK, project_id
  quantity                     numeric(18,4)   -- snapshot of BoqLineItem.boq_quantity, refreshable pre-submit (§5c), frozen at submit
  quantity_at_build            numeric(18,4)   -- the value first snapshotted, kept even after a refresh, so a diff is always visible
  direct_unit_cost             numeric(14,4), nullable until resolved
  source_currency              char(3)
  cost_source                  quotation_line | cost_library_rate | manual
  source_quotation_line_item_id  uuid, nullable FK -> quotation_line_items
  source_cost_item_rate_id       uuid, nullable FK -> cost_item_rates
  source_rate_as_of_date         date, nullable
  source_set_by, source_set_at, source_note   -- "who, why" for every source, not just manual
  fx_rate         numeric(14,6), nullable
  fx_rate_date    date, nullable
  fx_recorded_by  uuid, nullable
  plant_pct_override, overhead_pct_override, volatility_pct_override, markup_pct_override   numeric(6,4), each nullable
  -- populated only at submit (snapshot)
  unit_sell_rate   numeric(14,2), nullable   -- rounded, authoritative (§4) -- this is what's shown/exported, never adjusted for rounding
  line_amount      money, nullable           -- = round(unit_sell_rate * quantity, 2), exactly -- no exceptions, no residual line
  line_note   text, nullable
```

`cost_source=quotation_line` reuses whichever `QuotationLineItem` is
currently `accepted` for that `boq_line_item_id`; if more than one vendor's
line is accepted for the same BOQ item (bid leveling allows comparing
several before a decision), the draft-build step leaves that line
unresolved (`direct_unit_cost=NULL`) and a reviewer must call the
line-source endpoint to pick one explicitly — a settlement can never
silently average or auto-pick between competing accepted bids.
`cost_source=cost_library_rate` calls the existing
`app/services/costlib.py::get_rate_as_of()` unchanged (bi-temporal, as-of a
given date) — no new cost-library code needed. `cost_source=manual` is a
typed-in rate with a required note.

## 3. Percentage resolution

For each line and each of the four percentage types (`plant`, `overhead`,
`volatility`, `markup`):

```
resolved = line.<type>_pct_override
           if not None else
           trade_override[boq_line_item.trade_node_id].<type>_pct
           if that row exists and that field is not None else
           settlement.default_<type>_pct
```

A BOQ line with no `trade_node_id` can only ever use the project default
(no trade row can match it) — same as today's `BoqTolerance` per-trade
override pattern in Module B, reused deliberately for consistency.

## 4. Per-line formula and the authoritative rate rule

Per line, in Decimal, no intermediate rounding, to get the *model* sell
value:

```
base        = direct_unit_cost * quantity
plant       = base * plant_pct
overhead    = base * overhead_pct
subtotal_1  = base + plant + overhead
volatility  = subtotal_1 * volatility_pct
subtotal_2  = subtotal_1 + volatility
markup      = subtotal_2 * markup_pct
model_sell  = subtotal_2 + markup                    -- exact, full precision -- NOT what gets charged
```

**Rates are authoritative — corrected per the brief, replacing the original
proposal's residual/largest-line design.** The unit rate is the real
number, rounded once, and the amount is exactly that rate times quantity;
nothing is ever nudged on any one line to make totals foot:

```
unit_sell_rate = round(model_sell / quantity, 2)              -- the rate, and it is never adjusted afterwards
line_amount    = round(unit_sell_rate * quantity, 2)           -- exactly this, always -- no exceptions
tender_total   = Σ line_amount                                 -- the authoritative settled amount: approved, exported, charged
```

The settlement also stores, purely for audit/analytics, the gap between
that authoritative total and the theoretical exact-precision model total:

```
exact_model_total   = Σ model_sell                             -- full precision, never rounded per line
rounding_difference = tender_total − exact_model_total         -- can be positive or negative; stored, not corrected away
```

`margin_on_sell_pct = Σ markup (exact, full precision) / tender_total × 100`
— the numerator is the true modelled markup amount; the denominator is the
real money changing hands. `tender_total` is what's used for approval
routing (§2a) and everything client-facing (export, D2).

## 5. Worked example (recomputed under the rates-authoritative rule)

Project default percentages: `plant=2%`, `overhead=5%`, `volatility=3%`,
`markup=10%`. Trade override for **Earthworks**: `volatility=6%` (higher
ground/weather risk). Three lines:

| Line | Trade | Qty | Direct unit cost | Source | Overrides |
|---|---|---|---|---|---|
| L1 Excavation | Earthworks | 500 m³ | 45.00 | accepted quote | — (inherits trade volatility=6%) |
| L2 Blinding concrete | Concrete | 200 m³ | 380.00 | cost library, as-of today | — (all project defaults) |
| L3 Rebar supply | Concrete | 15,000 kg | 3.85 | accepted quote | `markup_pct_override=15%` |

| | L1 | L2 | L3 |
|---|---|---|---|
| base (direct cost) | 22,500.00 | 76,000.00 | 57,750.00 |
| plant (2%) | 450.00 | 1,520.00 | 1,155.00 |
| overhead (5%) | 1,125.00 | 3,800.00 | 2,887.50 |
| volatility (6% / 3% / 3%) | 1,444.50 | 2,439.60 | 1,853.775 |
| markup (10% / 10% / **15%**) | 2,551.95 | 8,375.96 | 9,546.94125 |
| model_sell (exact) | 28,071.45 | 92,135.56 | 73,193.21625 |
| **unit_sell_rate** (2dp, authoritative) | **56.14** | **460.68** | **4.88** |
| **line_amount** (= rate × qty) | **28,070.00** | **92,136.00** | **73,200.00** |

- `exact_model_total = 28,071.45 + 92,135.56 + 73,193.21625 = 193,400.22625`.
- `tender_total = 28,070.00 + 92,136.00 + 73,200.00 = 193,406.00` — the
  authoritative settled amount. (Note it can land on either side of the
  exact model total — here it's *higher*, because L3's large quantity
  amplifies its rate's rounding.)
- `rounding_difference = 193,406.00 − 193,400.22625 = 5.77` (stored as-is;
  nothing redistributes it).
- `Σ markup (exact) = 2,551.95 + 8,375.96 + 9,546.94125 = 20,474.85125`.
- `margin_on_sell_pct = 20,474.85125 / 193,406.00 × 100 = 10.586%`.
- Routing: `tender_total = 193,406.00` is far under AED 2,000,000, and
  `margin_on_sell_pct = 10.586%` is above the 8% floor → neither escalation
  condition fires → this settlement routes to `bd_director`.

No line's displayed `unit_sell_rate` is ever touched for rounding reasons —
`56.14`, `460.68`, `4.88` are exactly what a reviewer set and exactly what
gets exported in D2.

## 5a. Status lifecycle

```
draft -----------------> submitted --------> approved --------> won
  ^  (revise: new           |  (submit,         |  (all tiers      \--> lost
  |   version_no,           |   bd_director+)   |   decide=approve)
  |   lead_estimator+)      |                    |
  |                         v                    v
  \------------------ rejected            (won/lost is D2 scope --
                    (any tier             outcome-capture endpoints --
                     decide=reject)        but the enum/columns exist
                                            now so D1 needs no later ALTER)
```

| Transition | Trigger | Role | Notes |
|---|---|---|---|
| (none) → `draft` | `POST .../bid-settlements` | `lead_estimator+` | new version, lines auto-resolved per §2b |
| `draft` → `draft` | any line/default/override edit, or refresh-quantities (§5c) | `estimator+`/`lead_estimator+` per §7 | mutable only in this state |
| `draft` → `submitted` | `POST .../submit` | `bd_director+` | blocked by an unresolved line, a missing FX rate, or a stale quantity (§5c); snapshots §4, creates the `ApprovalRequest` |
| `submitted` → `approved` | last approval tier decides `approve` | tier's `required_role` (`bd_director` or `managing_director`, per §2a's routing) — **never the submitter** (§2a SoD) | `decided_at`/`decided_by` set; `tender_total` etc. are now final |
| `submitted` → `rejected` | any tier decides `reject` | same as above | terminal for this version; a revision is a new `draft` version (`version_no + 1`) |
| `approved` → `won` / `lost` | D2 outcome-capture | `bd_director+` | out of D1's scope; mentioned for schema completeness only |

A `rejected` settlement is never edited back to life — the only way forward
is `build_settlement_draft` creating the next version, same as `Quotation`.

## 5b. Segregation of duties

Enforced in the shared engine (§2a), not duplicated here: whoever's
`ctx.user_id` matches the `ApprovalRequest.requested_by` (i.e. whoever
called `submit`) gets `ForbiddenError` on any `decide()` call against that
request, even if their role would otherwise qualify for the required tier.
Tested explicitly (§7): a `bd_director` submits, that *same* `bd_director`
attempts to decide → 403; a *different* `bd_director` (or the escalated
`managing_director`, when routing requires it) → succeeds.

## 5c. Quantity check at submit (addenda)

BOQ quantities can change after a settlement draft was built (an addendum,
a takeoff correction). `submit` re-reads every included line's current
`BoqLineItem.boq_quantity` and compares it against the settlement line's
stored `quantity`. Any difference blocks submit (409) and returns the full
list of differing lines (`boq_line_item_id`, `quantity` (settlement's),
`current_boq_quantity`).

`POST .../refresh-quantities` (audited, `lead_estimator+`): sets every
differing line's `quantity` to the current BOQ value. It touches **only**
`quantity` — `direct_unit_cost`, `cost_source`, and every percentage
override are left exactly as they were. This is deliberate: a quantity
change and a cost/markup decision are independent judgement calls, and
silently invalidating a reviewer's cost entry because a quantity moved
would be worse than making them re-check it. `quantity_at_build` (§2b)
keeps the original number permanently so a diff is always reconstructable
even after refreshing.

## 6. Boundary tests (required by the brief, listed explicitly)

1. `tender_total = 2,000,000.00` exactly, margin comfortably above 8% →
   routes to `bd_director` (tier 1's inclusive bracket).
2. `tender_total = 2,000,000.01`, same margin → routes to
   `managing_director` (tier 2's bracket, one cent over).
3. `margin_on_sell_pct = 8.00` exactly, amount comfortably under AED 2M →
   routes to `bd_director` (strict `<`, not `<=`).
4. `margin_on_sell_pct = 7.99`, same amount → routes to
   `managing_director` (margin clause fires).
5. `tender_total = 0.00` (a settlement with all lines netting to zero, or a
   single zero-quantity/zero-cost line) → does not error; routes on margin
   alone (undefined/zero markup falls back to tier 1 unless a margin value
   is also supplied and under the floor).
6. Negative `markup_pct` (selling below landed cost) → `margin_on_sell_pct`
   is negative, which is `< 8` → routes to `managing_director`
   unconditionally, regardless of `tender_total`.

## 7. Endpoints

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/projects/{id}/bid-settlements` | `lead_estimator+` | builds a new draft version; auto-resolves lines per §2b |
| GET | `/bid-settlements/{id}` | `estimator+` | full detail, resolved per-line breakdown at current draft percentages |
| PATCH | `/bid-settlements/{id}/defaults` | `lead_estimator+` | project-level default percentages, currency |
| PUT | `/bid-settlements/{id}/trade-overrides/{trade_node_id}` | `lead_estimator+` | set/clear a trade's overrides |
| PATCH | `/bid-settlements/{id}/lines/{line_id}` | `estimator+` | set cost source (manual / pick accepted quote / pick cost-library rate as-of) and/or line-level pct overrides |
| POST | `/bid-settlements/{id}/lines/{line_id}/fx-rate` | `lead_estimator+` | records FX rate/date for a currency-mismatched line ("a reviewer records it") |
| POST | `/bid-settlements/{id}/refresh-quantities` | `lead_estimator+` | §5c; audited |
| POST | `/bid-settlements/{id}/simulate` | `estimator+` | stateless; body carries transient default/trade/line percentages; returns full breakdown incl. both `markup_pct` and derived `margin_on_sell_pct`, no DB writes |
| POST | `/bid-settlements/{id}/scenarios` | `estimator+` | optionally persists a named simulate result for comparison |
| GET | `/bid-settlements/{id}/scenarios` | `estimator+` | list saved scenarios |
| POST | `/bid-settlements/{id}/submit` | `bd_director+` | validates every line resolved, every currency mismatch has an FX rate, and every quantity matches the live BOQ (§5c); computes + snapshots §4; creates the `bid_settlement` approval request |
| POST | `/bid-settlements/{id}/decide` | whatever the routed tier requires (never the submitter) | thin wrapper over `approvals.decide()` that also syncs `bid_settlements.status`/`decided_at`/`decided_by` in the same transaction |

Submit blocks (409) if any line has `direct_unit_cost IS NULL`, a currency
mismatch with no `fx_rate`, or a stale quantity — naming every offending
line in each case.

## 8. Testing plan (mirrors the C1/C2 convention)

- Role tests per permission: lowest allowed role succeeds, one denied role
  (e.g. `estimator` for `PATCH .../defaults`) gets `ForbiddenError`.
- Unit tests for the resolution cascade (line > trade > default) and the
  §4/§5 formula — the exact worked-example numbers above as a fixture, plus
  a property-style test with many lines/quantities asserting
  `tender_total == Σ line_amount` always holds (trivially true by
  construction, but guards against a future refactor breaking it) and that
  `unit_sell_rate` is never mutated after being set.
- The six boundary tests in §6, each asserting the resulting `required_role`.
- Segregation-of-duties test: submitter denied on their own request;
  a different qualifying role succeeds. Run once for `bid_settlement` and
  once for `cost_rate_change` (the pre-existing-gap fix must cover both).
- Integration test that `submit` is blocked by an unresolved line, a
  missing FX rate, and a stale quantity — and unblocks once each is fixed
  (the last one via `refresh-quantities`).
- Integration test that a submitted settlement's lines/percentages are
  immutable (editing after submit is rejected), and that a new version can
  still be created after a `rejected` outcome.
- Dev simulation: `make dev-simulate-settlement`, exercising build → resolve
  lines → simulate → submit → decide (as a different user) end-to-end
  against the real dev stack, same as prior modules.
- `make test-unit` green at the end of the phase; `make test-integration`
  run against the real dev stack before merging.
- Verification written into `docs/build-log.md`'s Phase 1 section (this
  programme's convention replaces a separate verification-report doc per
  module — see the brief §0.2).

## 9. Explicitly out of scope for D1 (carried to D2 or later)

- Client BOQ export itself (D2).
- Win/loss capture endpoints (D2) — the `bid_settlements` columns for it
  are included now so D1's schema doesn't need a later ALTER.
- Retaining the client's original tender-BOQ workbook + per-row cell
  coordinates in Module B's import (D2, ahead of actually using it for a
  preserve-the-original export in D3).
