import { describe, expect, it } from 'vitest'
import {
  NO_FILTERS,
  classLabeler,
  classOptions,
  decidedByInfo,
  defaultExpanded,
  filterItems,
  folderSegments,
  formatUnitType,
  groupByFolder,
  groupByType,
  isBulkConfirmable,
  visibleFlags,
} from './treeLib'
import { TEST_CLASSES, treeItem } from './testFixtures'

const label = classLabeler(TEST_CLASSES)

describe('groupByType', () => {
  it('orders classes as specified and puts classless files last', () => {
    const items = [
      treeItem({ doc_class: 'other' }),
      treeItem({ doc_class: null }),
      treeItem({ doc_class: 'boq' }),
      treeItem({ doc_class: 'drawing' }),
      treeItem({ doc_class: 'specification' }),
    ]
    const nodes = groupByType(items, label)
    expect(nodes.map((n) => n.key)).toEqual(['class:drawing', 'class:boq', 'class:specification', 'class:other', 'class:none'])
    expect(nodes.at(-1)?.label).toBe('Not classified yet')
    expect(nodes[1].label).toBe('Bill of quantities')
  })

  it('puts unknown class codes after the known ones and before not-classified', () => {
    const nodes = groupByType([treeItem({ doc_class: 'mystery' }), treeItem({ doc_class: null }), treeItem({ doc_class: 'other' })], label)
    expect(nodes.map((n) => n.key)).toEqual(['class:other', 'class:mystery', 'class:none'])
    expect(nodes[1].label).toBe('Mystery')
  })

  it('nests drawings by discipline then drawing type, with counts rolling up', () => {
    const d = (discipline: string | null, drawing_type: string | null) => treeItem({ doc_class: 'drawing', discipline, drawing_type })
    const nodes = groupByType(
      [
        d('stormwater', 'plan_profile'),
        d('roads_civil', 'cross_sections'),
        d('roads_civil', 'plan_profile'),
        d('roads_civil', 'plan_profile'),
        d('roads_civil', null),
        d(null, null),
        d('civil_infra', 'schedules'),
      ],
      label,
    )
    const drawing = nodes[0]
    expect(drawing.count).toBe(7)
    expect(drawing.items).toHaveLength(0)
    expect(drawing.children.map((c) => [c.label, c.count])).toEqual([
      ['Roads / civil', 4],
      ['Stormwater drainage', 1],
      ['Civil / infrastructure', 1],
      ['Discipline not set', 1],
    ])
    const roads = drawing.children[0]
    expect(roads.children.map((c) => [c.label, c.count])).toEqual([
      ['Plan & profile / longitudinal section', 2],
      ['Cross sections', 1],
      ['Type not set', 1],
    ])
    expect(roads.children[0].items).toHaveLength(2)
    expect(drawing.ids).toHaveLength(7)
    expect(roads.children[0].depth).toBe(2)
  })

  it('keeps non-drawing classes flat and sorts files naturally by name', () => {
    const nodes = groupByType(
      ['b10.pdf', 'b2.pdf', 'a1.pdf'].map((name) => treeItem({ doc_class: 'specification', name })),
      label,
    )
    expect(nodes[0].children).toEqual([])
    expect(nodes[0].items.map((i) => i.name)).toEqual(['a1.pdf', 'b2.pdf', 'b10.pdf'])
  })

  it('returns nothing for no files', () => {
    expect(groupByType([], label)).toEqual([])
  })
})

describe('groupByFolder', () => {
  it('builds the upload folder tree and drops the file name', () => {
    const at = (path: string | null) => treeItem({ path, name: (path ?? 'x.pdf').split('/').pop() })
    const nodes = groupByFolder([
      at('Tender/Drawings/C-101.pdf'),
      at('Tender/Drawings/C-102.pdf'),
      at('Tender/Drawings/Roads/R-1.pdf'),
      at('Tender/BOQ.xlsx'),
      at('loose.pdf'),
      at(null),
    ])
    expect(nodes.map((n) => [n.label, n.count])).toEqual([
      ['Tender', 4],
      ['Top level (no folder)', 2],
    ])
    const tender = nodes[0]
    expect(tender.items.map((i) => i.name)).toEqual(['BOQ.xlsx'])
    expect(tender.children.map((c) => [c.label, c.count])).toEqual([['Drawings', 3]])
    expect(tender.children[0].children.map((c) => c.label)).toEqual(['Roads'])
    expect(tender.children[0].children[0].key).toBe('folder:/Tender/Drawings/Roads')
  })

  it('normalises backslashes', () => {
    expect(folderSegments('A\\B\\f.pdf')).toEqual(['A', 'B'])
    expect(folderSegments('f.pdf')).toEqual([])
    expect(folderSegments(null)).toEqual([])
  })
})

describe('filterItems', () => {
  const items = [
    treeItem({ name: 'C-101.pdf', path: 'Roads/C-101.pdf', doc_class: 'drawing', title: 'Plan and profile', document_number: 'RD-101', display_status: 'ready', decided_by: 'ai', auto_accepted: true }),
    treeItem({ name: 'boq.xlsx', doc_class: 'boq', display_status: 'needs_check', decided_by: null }),
    treeItem({ name: 'mystery.pdf', doc_class: null, display_status: 'reading' }),
    treeItem({ name: 'spec.pdf', doc_class: 'specification', display_status: 'ready', flags: ['rules_fallback'] }),
  ]

  it('returns the same array when no filter is set', () => {
    expect(filterItems(items, NO_FILTERS)).toBe(items)
  })

  it('searches name, path, number and title case-insensitively', () => {
    expect(filterItems(items, { ...NO_FILTERS, q: 'roads/' })).toHaveLength(1)
    expect(filterItems(items, { ...NO_FILTERS, q: 'rd-101' })).toHaveLength(1)
    expect(filterItems(items, { ...NO_FILTERS, q: 'PROFILE' })).toHaveLength(1)
    expect(filterItems(items, { ...NO_FILTERS, q: 'spec' })).toHaveLength(1)
    expect(filterItems(items, { ...NO_FILTERS, q: '  ' })).toBe(items)
  })

  it('filters by class, including the not-classified bucket, status and decided-by', () => {
    expect(filterItems(items, { ...NO_FILTERS, docClass: 'boq' }).map((i) => i.name)).toEqual(['boq.xlsx'])
    expect(filterItems(items, { ...NO_FILTERS, docClass: 'none' }).map((i) => i.name)).toEqual(['mystery.pdf'])
    expect(filterItems(items, { ...NO_FILTERS, status: 'ready' })).toHaveLength(2)
    expect(filterItems(items, { ...NO_FILTERS, decidedBy: 'ai' })).toHaveLength(1)
    expect(filterItems(items, { ...NO_FILTERS, decidedBy: 'rules' }).map((i) => i.name)).toEqual(['spec.pdf'])
    expect(filterItems(items, { ...NO_FILTERS, status: 'ready', q: 'c-101' })).toHaveLength(1)
    expect(filterItems(items, { ...NO_FILTERS, status: 'failed' })).toHaveLength(0)
  })
})

describe('decided-by, flags and labels', () => {
  it('maps the decider to a badge', () => {
    expect(decidedByInfo(treeItem({ decided_by: 'ai', auto_accepted: true }))?.label).toBe('AI (auto-accepted)')
    expect(decidedByInfo(treeItem({ decided_by: 'ai' }))?.label).toBe('AI')
    expect(decidedByInfo(treeItem({ decided_by: 'user', flags: ['rules_fallback'] }))?.label).toBe('You')
    expect(decidedByInfo(treeItem({ decided_by: 'rules' }))?.label).toBe('Classified by rules')
    expect(decidedByInfo(treeItem({ flags: ['rules_fallback'] }))?.key).toBe('rules')
    expect(decidedByInfo(treeItem())).toBeNull()
  })

  it('hides rules_fallback from the flag list and tones the rest', () => {
    const flags = visibleFlags(treeItem({ flags: ['rules_fallback', 'conflict', 'duplicate'] }))
    expect(flags).toEqual([
      { flag: 'conflict', tone: 'danger' },
      { flag: 'duplicate', tone: 'neutral' },
    ])
  })

  it('bulk-confirm skips conflict and injection files', () => {
    expect(isBulkConfirmable(treeItem({ flags: ['low_confidence'] }))).toBe(true)
    expect(isBulkConfirmable(treeItem({ flags: ['conflict'] }))).toBe(false)
    expect(isBulkConfirmable(treeItem({ flags: ['injection_suspected'] }))).toBe(false)
  })

  it('formats unit types and class options', () => {
    expect(formatUnitType('type_2')).toBe('Type 2')
    expect(formatUnitType('Type 10')).toBe('Type 10')
    expect(formatUnitType('villa_a')).toBe('Villa a')
    expect(classOptions([]).map((c) => c.code)[0]).toBe('drawing')
    expect(classOptions([]).map((c) => c.code)).toHaveLength(12)
    const opts = classOptions([
      { code: 'other', label: 'Misc', default_label: 'Other', enabled: true, sort_order: 1 },
      { code: 'boq', label: 'BOQ', default_label: 'BOQ', enabled: false, sort_order: 2 },
      { code: 'drawing', label: 'Drawings', default_label: 'Drawing', enabled: true, sort_order: 3 },
    ])
    expect(opts.map((o) => o.code)).toEqual(['drawing', 'other'])
  })
})

describe('300+ files', () => {
  const items = Array.from({ length: 360 }, (_, i) =>
    i % 3 === 0
      ? treeItem({ doc_class: 'drawing', discipline: i % 2 === 0 ? 'roads_civil' : 'sewer', drawing_type: 'plan_profile', path: `Tender/Drawings/S-${i}.pdf`, name: `S-${i}.pdf` })
      : treeItem({ doc_class: i % 3 === 1 ? 'specification' : null, path: `Tender/Docs/d-${i}.pdf`, name: `d-${i}.pdf` }),
  )

  it('groups every file exactly once in both views', () => {
    const byType = groupByType(items, label)
    expect(byType.reduce((n, g) => n + g.count, 0)).toBe(360)
    expect(byType.flatMap((g) => g.ids)).toHaveLength(360)
    expect(new Set(byType.flatMap((g) => g.ids)).size).toBe(360)
    const folders = groupByFolder(items)
    expect(folders).toHaveLength(1)
    expect(folders[0].count).toBe(360)
    expect(folders[0].children.map((c) => c.label)).toEqual(['Docs', 'Drawings'])
  })

  it('opens only drawings and BOQ by default on a large tree, everything on a small one', () => {
    const nodes = groupByType(items, label)
    const opts = { filtering: false, total: 360 }
    expect(defaultExpanded(nodes[0], 'type', opts)).toBe(true)
    expect(defaultExpanded(nodes[0].children[0], 'type', opts)).toBe(true)
    expect(defaultExpanded(nodes[0].children[0].children[0], 'type', opts)).toBe(false)
    const spec = nodes.find((n) => n.key === 'class:specification')
    expect(spec && defaultExpanded(spec, 'type', opts)).toBe(false)
    expect(spec && defaultExpanded(spec, 'type', { filtering: true, total: 360 })).toBe(true)
    expect(spec && defaultExpanded(spec, 'type', { filtering: false, total: 10 })).toBe(true)
    const folders = groupByFolder(items)
    expect(defaultExpanded(folders[0], 'folder', opts)).toBe(true)
    expect(defaultExpanded(folders[0].children[0], 'folder', opts)).toBe(false)
  })
})
