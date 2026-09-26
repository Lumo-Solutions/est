// Three confidence bands for the measurement overlay's colour coding. These
// thresholds are a UI-only convention (not a business rule -- the backend
// never gates on them) documented here so they're easy to find and adjust.
export type ConfidenceBand = 'high' | 'medium' | 'low'

const HIGH_THRESHOLD = 0.8
const MEDIUM_THRESHOLD = 0.5

export function confidenceBand(confidence: number): ConfidenceBand {
  if (confidence >= HIGH_THRESHOLD) return 'high'
  if (confidence >= MEDIUM_THRESHOLD) return 'medium'
  return 'low'
}

const BAND_COLORS: Record<ConfidenceBand, string> = {
  high: '#16a34a', // green-600
  medium: '#d97706', // amber-600
  low: '#dc2626', // red-600
}

export function confidenceColor(confidence: number): string {
  return BAND_COLORS[confidenceBand(confidence)]
}
