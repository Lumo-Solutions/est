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
