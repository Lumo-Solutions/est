import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useRef } from 'react'
import { Button } from '../../components/Button'

const NEAR_END = 5

// A scrollable, virtualised list of server-paged rows. Only the rows near the viewport are in the DOM (row heights
// vary, so each one is measured), the next page loads when the user scrolls near the end, and "N of M shown" with a
// "Load more" button is the accessible fallback.
export function VirtualRows<T>({
  label,
  items,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
  getKey,
  renderRow,
  estimateSize = 72,
  maxHeight = '28rem',
}: {
  label: string
  items: T[]
  total: number
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
  getKey: (item: T) => string
  renderRow: (item: T) => React.ReactNode
  estimateSize?: number
  maxHeight?: string
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    overscan: 6,
    getItemKey: (i) => getKey(items[i]),
  })
  const virtualItems = virtualizer.getVirtualItems()
  const lastIndex = virtualItems.length > 0 ? virtualItems[virtualItems.length - 1].index : -1

  useEffect(() => {
    if (hasMore && !loadingMore && lastIndex >= items.length - NEAR_END) onLoadMore()
  }, [hasMore, loadingMore, lastIndex, items.length, onLoadMore])

  return (
    <div>
      <div ref={scrollRef} style={{ maxHeight, overflowY: 'auto' }} className="rounded-control border border-row-rule">
        <div role="list" aria-label={label} style={{ height: virtualizer.getTotalSize(), position: 'relative', width: '100%' }}>
          {virtualItems.map((v) => (
            <div
              key={v.key}
              role="listitem"
              data-index={v.index}
              ref={virtualizer.measureElement}
              className="border-b border-row-rule px-2"
              style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${v.start}px)` }}
            >
              {renderRow(items[v.index])}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <p className="text-sm text-ink-2">
          {items.length} of {total} shown
        </p>
        {hasMore && (
          <Button variant="secondary" size="sm" loading={loadingMore} onClick={onLoadMore}>
            Load more
          </Button>
        )}
      </div>
    </div>
  )
}
