import { describe, expect, it } from 'vitest'
import type { DrawingEntityOut } from '../../types/api'
import { bulgeArcPoints, entitiesToSvgPaths, entityToPolylines } from './dxfGeometry'

function entity(overrides: Partial<DrawingEntityOut>): DrawingEntityOut {
  return {
    id: 'e1',
    sheet_id: 's1',
    source: 'dxf',
    entity_type: 'line',
    layer: 'C-ROAD',
    block_name: null,
    text_value: null,
    bbox_min_x: null,
    bbox_min_y: null,
    bbox_max_x: null,
    bbox_max_y: null,
    geometry: null,
    handle: null,
    ...overrides,
  }
}

describe('bulgeArcPoints', () => {
  it('a bulge of 1.0 (a semicircle) traversed CCW from p1 to p2 bulges below the chord', () => {
    // p1=(0,0), p2=(1,0): the CCW semicircle's apex must be at (0.5, -0.5)
    // -- see dxfGeometry.ts's comment for the worked derivation.
    const points = bulgeArcPoints([0, 0], [1, 0], 1, 24)
    const apex = points[Math.floor(points.length / 2) - 1]
    expect(apex[0]).toBeCloseTo(0.5, 1)
    expect(apex[1]).toBeCloseTo(-0.5, 1)
    // last tessellated point is always p2
    const last = points[points.length - 1]
    expect(last[0]).toBeCloseTo(1, 10)
    expect(last[1]).toBeCloseTo(0, 10)
  })

  it('a negative bulge sweeps to the opposite side of the chord', () => {
    const ccw = bulgeArcPoints([0, 0], [1, 0], 1, 24)
    const cw = bulgeArcPoints([0, 0], [1, 0], -1, 24)
    const ccwApex = ccw[Math.floor(ccw.length / 2) - 1]
    const cwApex = cw[Math.floor(cw.length / 2) - 1]
    expect(Math.sign(ccwApex[1])).not.toBe(Math.sign(cwApex[1]))
  })

  it('zero bulge is just the straight segment to p2', () => {
    expect(bulgeArcPoints([0, 0], [3, 4], 0)).toEqual([[3, 4]])
  })
})

describe('entityToPolylines', () => {
  it('a line entity (two vertices, no bulge) is a two-point polyline', () => {
    const line = entity({
      entity_type: 'line',
      geometry: { vertices: [[0, 0], [10, 0]], closed: false, bulges: null, center: null, radius: null, start_angle_deg: null, end_angle_deg: null },
    })
    const polylines = entityToPolylines(line)
    expect(polylines).toHaveLength(1)
    expect(polylines[0][0]).toEqual([0, 0])
    expect(polylines[0][polylines[0].length - 1]).toEqual([10, 0])
  })

  it('a quarter-circle arc entity (center/radius/angles) tessellates from the start to end angle', () => {
    const arc = entity({
      entity_type: 'arc',
      geometry: { vertices: [], closed: false, bulges: null, center: [0, 0], radius: 5, start_angle_deg: 0, end_angle_deg: 90 },
    })
    const [points] = entityToPolylines(arc)
    expect(points[0]).toEqual([5, 0])
    const last = points[points.length - 1]
    expect(last[0]).toBeCloseTo(0, 5)
    expect(last[1]).toBeCloseTo(5, 5)
  })

  it('a full circle entity (center/radius, no angles) tessellates a closed loop', () => {
    const circle = entity({
      entity_type: 'circle',
      geometry: { vertices: [], closed: false, bulges: null, center: [2, 3], radius: 4, start_angle_deg: null, end_angle_deg: null },
    })
    const [points] = entityToPolylines(circle)
    const first = points[0]
    const last = points[points.length - 1]
    expect(last[0]).toBeCloseTo(first[0], 10)
    expect(last[1]).toBeCloseTo(first[1], 10)
    for (const [x, y] of points) {
      expect(Math.hypot(x - 2, y - 3)).toBeCloseTo(4, 5)
    }
  })

  it('a bulged polyline segment tessellates through the correct arc', () => {
    const polyline = entity({
      entity_type: 'lwpolyline',
      geometry: {
        vertices: [[0, 0], [1, 0], [1, 1]],
        closed: false,
        bulges: [1, 0],
        center: null,
        radius: null,
        start_angle_deg: null,
        end_angle_deg: null,
      },
    })
    const [points] = entityToPolylines(polyline)
    // first segment (0,0)->(1,0) with bulge=1 is a semicircle dipping to
    // (0.5,-0.5); second segment (1,0)->(1,1) is straight (bulge=0).
    const dip = points.find((p) => Math.abs(p[0] - 0.5) < 0.05)
    expect(dip?.[1]).toBeLessThan(0)
    expect(points[points.length - 1]).toEqual([1, 1])
  })

  it('an entity with no geometry produces no polylines', () => {
    expect(entityToPolylines(entity({ geometry: null }))).toEqual([])
  })
})

describe('entitiesToSvgPaths', () => {
  it('produces one path per entity and a viewBox covering all of them, flipping y', () => {
    const line = entity({
      id: 'a',
      geometry: { vertices: [[0, 0], [10, 20]], closed: false, bulges: null, center: null, radius: null, start_angle_deg: null, end_angle_deg: null },
    })
    const { paths, viewBox } = entitiesToSvgPaths([line])
    expect(paths).toHaveLength(1)
    expect(paths[0].d).toBe('M 0 0 L 10 -20')
    const [minX, minY, width, height] = viewBox.split(' ').map(Number)
    expect(minX).toBeLessThanOrEqual(0)
    expect(minY).toBeLessThanOrEqual(-20)
    expect(width).toBeGreaterThan(10)
    expect(height).toBeGreaterThan(20)
  })

  it('returns an empty path list and a default viewBox for no entities', () => {
    expect(entitiesToSvgPaths([])).toEqual({ paths: [], viewBox: '0 0 100 100' })
  })
})
