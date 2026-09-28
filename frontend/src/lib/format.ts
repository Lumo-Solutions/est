// Decimal precision margin-on-sell is displayed at wherever it drives
// approval routing (cockpit live simulation, the approval screen,
// submit's response) -- app/services/approvals.py routes on the exact
// Decimal value margin_on_sell_pct is quantized to (3dp), so a 2dp display
// could round a value like 7.995 up to "8.00" and hide that it actually
// escalated past the bd_director floor to managing_director. See
// docs/build-log.md's Phase 10 section for the decision.
export const MARGIN_PCT_DECIMALS = 3

export function formatMarginPct(value: number): string {
  return value.toFixed(MARGIN_PCT_DECIMALS)
}

// docs/ui-qa-brief.md's money rule: thousands separators, 2dp, currency
// code shown (not a "$"-style symbol -- this app deals in AED, occasionally
// other currencies on a quotation, never USD by default). No shared
// formatter existed anywhere in the frontend before this (see
// docs/ui-qa/issues.md's Phase 2 cross-cutting note) -- used here for the
// settlement per-trade/per-line override UI (Phase 3 gap-fill); a broader
// pass to use this everywhere else money is displayed belongs to Phase 4.
const AED_FORMATTER = new Intl.NumberFormat('en-AE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function formatMoney(value: number, currency = 'AED'): string {
  return `${currency} ${AED_FORMATTER.format(value)}`
}
