import { describe, expect, it } from 'vitest'
import { TEST_CLASSES, groupCount, treeItem, treeSummary } from './testFixtures'
import {
  CONFIRM_ALL_FILTER,
  NO_FILTERS,
  buildFolderNodes,
  buildTypeNodes,
  capList,
  classLabeler,
  classOptions,
  decidedByInfo,
  defaultExpanded,
  flagText,
  formatUnitType,
  isFiltering,
  isIntakeBusy,
  toDocFilter,
  visibleFlags,
} from './treeLib'

const label = classLabeler(TEST_CLASSES)
const summaryRows = (nodes: { label: string; count: number }[]) => nodes.map((n) => [n.label, n.count])

describe('buildTypeNodes (from counts only)', () => {
  it('orders classes as specified and puts classless files last', () => {
    const nodes = buildTypeNodes(
      [groupCount(null, 1), groupCount('specification', 1), groupCount('boq', 2), groupCount('drawing', 3, 'roads_civil', 'plan_profile'), groupCount('addendum', 1)],
      label,
    )
    expect(summaryRows(nodes)).toEqual([
      ['Drawing', 3],
      ['Bill of quantities', 2],
      ['Addendum', 1],
      ['Specification', 1],
      ['Not classified yet', 1],
    ])
    expect(nodes.at(-1)?.listFilter).toEqual({ doc_class: 'none' })
  })

  it('puts unknown class codes after the known ones and before not-classified', () => {
    const nodes = buildTypeNodes([groupCount(null, 1), groupCount('zzz_custom', 1), groupCount('boq', 1)], label)
    expect(nodes.map((n) => n.key)).toEqual(['class:boq', 'class:zzz_custom', 'class:none'])
  })

  it('nests drawings by discipline then drawing type, with counts rolled up and filters that match the counts', () => {
    const nodes = buildTypeNodes(
      [
        groupCount('drawing', 5, 'roads_civil', 'plan_profile'),
        groupCount('drawing', 2, 'roads_civil', 'cross_sections'),
        groupCount('drawing', 1, 'roads_civil', null),
        groupCount('drawing', 3, 'stormwater', 'plan_profile'),
        groupCount('drawing', 4, null, null),
      ],
      label,
    )
    expect(nodes).toHaveLength(1)
    const drawing = nodes[0]
    expect(drawing.count).toBe(15)
    expect(drawing.listFilter).toBeNull()
    expect(drawing.selectFilter).toEqual({ doc_class: 'drawing' })
    expect(summaryRows(drawing.children)).toEqual([
      ['Roads / civil', 8],
      ['Stormwater drainage', 3],
      ['Discipline not set', 4],
    ])
    const roads = drawing.children[0]
    expect(roads.selectFilter).toEqual({ doc_class: 'drawing', discipline: 'roads_civil' })
    expect(summaryRows(roads.children)).toEqual([
      ['Plan & profile / longitudinal section', 5],
      ['Cross sections', 2],
      ['Type not set', 1],
    ])
    expect(roads.children[0].listFilter).toEqual({ doc_class: 'drawing', discipline: 'roads_civil', drawing_type: 'plan_profile' })
    expect(roads.children[2].listFilter).toEqual({ doc_class: 'drawing', discipline: 'roads_civil', drawing_type: 'none' })
    expect(drawing.children[2].children[0].listFilter).toEqual({ doc_class: 'drawing', discipline: 'none', drawing_type: 'none' })
    expect(drawing.classHint).toBe('drawing')
  })

  it('keeps non-drawing classes flat, summing any split rows, and drops empty rows', () => {
    const nodes = buildTypeNodes([groupCount('boq', 2), groupCount('boq', 3, 'x', null), groupCount('other', 0)], label)
    expect(summaryRows(nodes)).toEqual([['Bill of quantities', 5]])
    expect(nodes[0].children).toEqual([])
    expect(nodes[0].listFilter).toEqual({ doc_class: 'boq' })
  })

  it('returns nothing for no counts', () => {
    expect(buildTypeNodes([], label)).toEqual([])
  })
})

describe('buildFolderNodes (from the folder -> count map)', () => {
  it('builds the folder tree, rolls counts up, and lists a folder own files with an exact folder filter', () => {
    const nodes = buildFolderNodes([
      { folder: 'Tender/Drawings/Roads', count: 4 },
      { folder: 'Tender/Drawings', count: 1 },
      { folder: 'Tender/Specs', count: 2 },
      { folder: 'loose', count: 1 },
      { folder: '', count: 3 },
    ])
    expect(summaryRows(nodes)).toEqual([
      ['loose', 1],
      ['Tender', 7],
      ['Top level (no folder)', 3],
    ])
    const tender = nodes[1]
    expect(tender.directCount).toBe(0)
    expect(tender.listFilter).toBeNull()
    expect(tender.selectFilter).toEqual({ folder: 'Tender', include_subfolders: true })
    expect(summaryRows(tender.children)).toEqual([
      ['Drawings', 5],
      ['Specs', 2],
    ])
    const drawings = tender.children[0]
    expect(drawings.directCount).toBe(1)
    expect(drawings.listFilter).toEqual({ folder: 'Tender/Drawings' })
    expect(drawings.children[0].listFilter).toEqual({ folder: 'Tender/Drawings/Roads' })
    expect(nodes[2].listFilter).toEqual({ folder: '' })
    expect(nodes[2].selectFilter).toEqual({ folder: '' })
  })

  it('normalises backslashes and ignores empty counts', () => {
    const nodes = buildFolderNodes([
      { folder: 'A\\B', count: 2 },
      { folder: 'C', count: 0 },
    ])
    expect(nodes.map((n) => n.label)).toEqual(['A'])
    expect(nodes[0].children[0].listFilter).toEqual({ folder: 'A/B' })
  })
})

describe('server-side filters', () => {
  it('maps the search box and selects to the /items filter', () => {
    expect(toDocFilter(NO_FILTERS)).toEqual({})
    expect(toDocFilter({ q: ' rd-101 ', docClass: 'none', status: 'failed', decidedBy: 'user' })).toEqual({
      q: 'rd-101',
      doc_class: 'none',
      display_status: 'failed',
      decided_by: 'user',
    })
    expect(isFiltering(NO_FILTERS)).toBe(false)
    expect(isFiltering({ ...NO_FILTERS, q: '  ' })).toBe(false)
    expect(isFiltering({ ...NO_FILTERS, status: 'ready' })).toBe(true)
  })

  it('Confirm all holds back conflict and injection files and files with no class', () => {
    expect(CONFIRM_ALL_FILTER).toEqual({ display_status: 'needs_check', has_class: true, exclude_flags: ['conflict', 'injection_suspected'] })
  })
})

describe('decided-by, flags and labels', () => {
  it('maps the decider to a badge', () => {
    expect(decidedByInfo(treeItem({ decided_by: 'user' }))?.label).toBe('You')
    expect(decidedByInfo(treeItem({ decided_by: 'ai', auto_accepted: true }))?.label).toBe('AI (auto-accepted)')
    expect(decidedByInfo(treeItem({ decided_by: 'ai' }))?.label).toBe('AI')
    expect(decidedByInfo(treeItem({ flags: ['rules_fallback'] }))?.key).toBe('rules')
    expect(decidedByInfo(treeItem())).toBeNull()
  })

  it('hides rules_fallback from the flag list and tones the rest', () => {
    const item = treeItem({ flags: ['rules_fallback', 'conflict', 'too_large', 'duplicate'] })
    expect(visibleFlags(item)).toEqual([
      { flag: 'conflict', tone: 'danger' },
      { flag: 'too_large', tone: 'warning' },
      { flag: 'duplicate', tone: 'neutral' },
    ])
  })

  it('labels the too_large flag', () => {
    expect(flagText('too_large')).toBe('Too large')
    expect(flagText('conflict')).toBe('Conflict')
  })

  it('formats unit types, class options and the failure cap', () => {
    expect(formatUnitType('type_2')).toBe('Type 2')
    expect(classOptions([]).map((o) => o.code)[0]).toBe('drawing')
    expect(classOptions(TEST_CLASSES.map((c) => (c.code === 'other' ? { ...c, enabled: false } : c))).map((o) => o.code)).not.toContain('other')
    expect(capList(Array.from({ length: 25 }, (_, i) => i), 20)).toEqual({ shown: Array.from({ length: 20 }, (_, i) => i), more: 5 })
    expect(capList([1, 2], 20)).toEqual({ shown: [1, 2], more: 0 })
  })

  it('knows when intake is busy', () => {
    expect(isIntakeBusy(treeSummary())).toBe(false)
    expect(isIntakeBusy(treeSummary({ pending_upload: 1 }))).toBe(true)
    expect(isIntakeBusy(treeSummary({ in_progress: 1 }))).toBe(true)
    expect(isIntakeBusy(treeSummary({ packages_processing: 1 }))).toBe(true)
  })
})

describe('default expansion', () => {
  const groups = [
    groupCount('drawing', 800, 'roads_civil', 'plan_profile'),
    groupCount('boq', 5),
    groupCount('specification', 700),
    groupCount(null, 4),
  ]
  it('opens only drawings, BOQ and drawing disciplines on a large tree, everything on a small one', () => {
    const nodes = buildTypeNodes(groups, label)
    const big = { total: 2000 }
    const drawing = nodes[0]
    expect(defaultExpanded(drawing, 'type', big)).toBe(true)
    expect(defaultExpanded(drawing.children[0], 'type', big)).toBe(true)
    expect(defaultExpanded(drawing.children[0].children[0], 'type', big)).toBe(false)
    expect(defaultExpanded(nodes[1], 'type', big)).toBe(true)
    expect(defaultExpanded(nodes[2], 'type', big)).toBe(false)
    expect(defaultExpanded(nodes[2], 'type', { total: 30 })).toBe(true)
    const folders = buildFolderNodes([{ folder: 'A/B', count: 1 }])
    expect(defaultExpanded(folders[0], 'folder', big)).toBe(true)
    expect(defaultExpanded(folders[0].children[0], 'folder', big)).toBe(false)
  })

  it('builds a 2,000-file tree from a handful of count rows without any file list', () => {
    const nodes = buildTypeNodes([groupCount('drawing', 1200, 'roads_civil', 'plan_profile'), groupCount('specification', 800)], label)
    expect(nodes.reduce((n, x) => n + x.count, 0)).toBe(2000)
  })
})
