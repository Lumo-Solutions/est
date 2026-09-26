// Pure, DOM-free conversion of the backend's entity geometry (see
// backend/app/schemas/drawings.py::DrawingEntityOut and
// app/takeoff/dxf.py's GeometricEntity, which this mirrors) into SVG path
// data, tessellating every arc (bulge segments, circles, and DXF ARC
// entities) into straight-line segments rather than using SVG's elliptical
// arc command -- that sidesteps large-arc/sweep-flag sign derivation
// entirely, at the cost of a very slightly non-smooth curve that is
// irrelevant for a takeoff overlay (measurement precision comes from the
// backend's own geometry math, never from pixel-perfect rendering).
import type { DrawingEntityOut } from '../../types/api'

export type Point = [number, number]

const ARC_SEGMENTS = 24

function dist(a: Point, b: Point): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1])
}

function normalizeAngle(a: number): number {
  const twoPi = 2 * Math.PI
  return ((a % twoPi) + twoPi) % twoPi
}

/** Circumcenter of three non-collinear points. */
export function circumcenter(p1: Point, p2: Point, p3: Point): Point {
  const [x1, y1] = p1
  const [x2, y2] = p2
  const [x3, y3] = p3
  const d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
  const sq1 = x1 * x1 + y1 * y1
  const sq2 = x2 * x2 + y2 * y2
  const sq3 = x3 * x3 + y3 * y3
  const ux = (sq1 * (y2 - y3) + sq2 * (y3 - y1) + sq3 * (y1 - y2)) / d
  const uy = (sq1 * (x3 - x2) + sq2 * (x1 - x3) + sq3 * (x2 - x1)) / d
  return [ux, uy]
}

/** Tessellates a circular arc from `start` to `end`, sweeping through the
 * `apex` (the arc's own midpoint) -- the direction that makes it pass
 * through apex is inferred rather than assumed. Excludes `start`, includes
 * `end` (so segments concatenate cleanly onto a running polyline). */
export function tessellateArcThroughApex(start: Point, apex: Point, end: Point, segments = ARC_SEGMENTS): Point[] {
  const center = circumcenter(start, apex, end)
  const radius = dist(center, start)
  const startAngle = normalizeAngle(Math.atan2(start[1] - center[1], start[0] - center[0]))
  const endAngle = normalizeAngle(Math.atan2(end[1] - center[1], end[0] - center[0]))
  const apexAngle = normalizeAngle(Math.atan2(apex[1] - center[1], apex[0] - center[0]))

  const ccwSweep = normalizeAngle(endAngle - startAngle)
  const apexOffset = normalizeAngle(apexAngle - startAngle)
  const goesCcw = apexOffset <= ccwSweep || ccwSweep === 0

  const sweep = goesCcw ? ccwSweep || 2 * Math.PI : -(2 * Math.PI - ccwSweep || 2 * Math.PI)

  const points: Point[] = []
  for (let i = 1; i <= segments; i++) {
    const angle = startAngle + (sweep * i) / segments
    points.push([center[0] + radius * Math.cos(angle), center[1] + radius * Math.sin(angle)])
  }
  return points
}

/** A DXF LWPOLYLINE-style bulge: tan(included_angle / 4), signed by sweep
 * direction (positive = counterclockwise). Returns the arc from p1 to p2,
 * excluding p1. */
export function bulgeArcPoints(p1: Point, p2: Point, bulge: number, segments = ARC_SEGMENTS): Point[] {
  if (bulge === 0) return [p2]
  const mid: Point = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2]
  const chordDx = p2[0] - p1[0]
  const chordDy = p2[1] - p1[1]
  const chordLen = Math.hypot(chordDx, chordDy)
  if (chordLen === 0) return [p2]
  // Positive bulge = the arc is traversed CCW from p1 to p2 (DXF
  // convention), which bulges to the RIGHT of the p1->p2 direction, not
  // the left -- verified against the p1=(0,0), p2=(1,0), bulge=1
  // (a semicircle) case: the CCW arc's apex is at (0.5, -0.5), below the
  // chord, i.e. clockwise-rotated (not CCW-rotated) from the direction
  // of travel.
  const perpUnit: Point = [chordDy / chordLen, -chordDx / chordLen]
  const sagitta = (bulge * chordLen) / 2
  const apex: Point = [mid[0] + perpUnit[0] * sagitta, mid[1] + perpUnit[1] * sagitta]
  return tessellateArcThroughApex(p1, apex, p2, segments)
}

function tessellateFullCircle(center: Point, radius: number, segments = ARC_SEGMENTS * 2): Point[] {
  const points: Point[] = []
  for (let i = 0; i <= segments; i++) {
    const angle = (2 * Math.PI * i) / segments
    points.push([center[0] + radius * Math.cos(angle), center[1] + radius * Math.sin(angle)])
  }
  return points
}

function tessellateArcByAngles(center: Point, radius: number, startDeg: number, endDeg: number, segments = ARC_SEGMENTS): Point[] {
  const start = (startDeg * Math.PI) / 180
  let end = (endDeg * Math.PI) / 180
  if (end < start) end += 2 * Math.PI
  const points: Point[] = []
  for (let i = 0; i <= segments; i++) {
    const angle = start + ((end - start) * i) / segments
    points.push([center[0] + radius * Math.cos(angle), center[1] + radius * Math.sin(angle)])
  }
  return points
}

/** Converts one entity's geometry into one or more point-array polylines
 * (already tessellated -- straight segments only). Returns [] for an
 * entity with no usable geometry (e.g. TEXT, or geometry: null). */
export function entityToPolylines(entity: DrawingEntityOut): Point[][] {
  const geom = entity.geometry
  if (!geom) return []

  if (geom.center && geom.radius != null) {
    if (geom.start_angle_deg != null && geom.end_angle_deg != null) {
      return [tessellateArcByAngles(geom.center, geom.radius, geom.start_angle_deg, geom.end_angle_deg)]
    }
    return [tessellateFullCircle(geom.center, geom.radius)]
  }

  if (geom.vertices && geom.vertices.length >= 2) {
    const points: Point[] = [geom.vertices[0]]
    for (let i = 0; i < geom.vertices.length - 1; i++) {
      const bulge = geom.bulges?.[i] ?? 0
      const p1 = geom.vertices[i]
      const p2 = geom.vertices[i + 1]
      points.push(...(bulge ? bulgeArcPoints(p1, p2, bulge) : [p2]))
    }
    if (geom.closed) {
      const bulge = geom.bulges?.[geom.vertices.length - 1] ?? 0
      const last = geom.vertices[geom.vertices.length - 1]
      const first = geom.vertices[0]
      points.push(...(bulge ? bulgeArcPoints(last, first, bulge) : [first]))
    }
    return [points]
  }

  return []
}

function pointsToPathD(points: Point[]): string {
  if (points.length === 0) return ''
  const [first, ...rest] = points
  // y negated: DXF is y-up, SVG is y-down -- see module docstring above.
  const cmd = [`M ${first[0]} ${-first[1]}`]
  for (const p of rest) cmd.push(`L ${p[0]} ${-p[1]}`)
  return cmd.join(' ')
}

export interface EntityPath {
  id: string
  layer: string | null
  d: string
}

export interface SvgConversionResult {
  paths: EntityPath[]
  viewBox: string
}

const VIEWBOX_PADDING_RATIO = 0.05

export function entitiesToSvgPaths(entities: DrawingEntityOut[]): SvgConversionResult {
  const paths: EntityPath[] = []
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity

  for (const entity of entities) {
    const polylines = entityToPolylines(entity)
    if (polylines.length === 0) continue
    const d = polylines.map(pointsToPathD).join(' ')
    paths.push({ id: entity.id, layer: entity.layer, d })
    for (const line of polylines) {
      for (const [x, y] of line) {
        const flippedY = -y
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (flippedY < minY) minY = flippedY
        if (flippedY > maxY) maxY = flippedY
      }
    }
  }

  if (!Number.isFinite(minX)) {
    return { paths, viewBox: '0 0 100 100' }
  }

  const width = maxX - minX || 1
  const height = maxY - minY || 1
  const padX = width * VIEWBOX_PADDING_RATIO
  const padY = height * VIEWBOX_PADDING_RATIO
  const viewBox = `${minX - padX} ${minY - padY} ${width + padX * 2} ${height + padY * 2}`
  return { paths, viewBox }
}
