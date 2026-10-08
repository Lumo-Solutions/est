import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockElementSizes } from './virtualTestUtils'
import { VirtualRows } from './VirtualRows'

mockElementSizes({ viewport: 448, row: 64 })

const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `r${i}`, name: `row-${i}` }))

describe('VirtualRows', () => {
  it('renders only the rows near the viewport of a 2,000-row list', () => {
    const { container } = render(
      <VirtualRows
        label="Big list"
        items={rows(2000)}
        total={2000}
        hasMore={false}
        loadingMore={false}
        onLoadMore={() => {}}
        getKey={(r) => r.id}
        renderRow={(r) => <span>{r.name}</span>}
      />,
    )
    const rendered = container.querySelectorAll('[role="listitem"]').length
    expect(rendered).toBeGreaterThan(0)
    expect(rendered).toBeLessThan(40)
    expect(screen.getByText('row-0')).toBeInTheDocument()
    expect(screen.queryByText('row-1500')).not.toBeInTheDocument()
    expect(screen.getByText('2000 of 2000 shown')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Big list' })).toBeInTheDocument()
  })

  it('has a visible Load more button as the accessible fallback', () => {
    const onLoadMore = vi.fn()
    render(
      <VirtualRows
        label="Pages"
        items={rows(100)}
        total={2000}
        hasMore
        loadingMore={false}
        onLoadMore={onLoadMore}
        getKey={(r) => r.id}
        renderRow={(r) => <span>{r.name}</span>}
      />,
    )
    expect(screen.getByText('100 of 2000 shown')).toBeInTheDocument()
    onLoadMore.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('asks for the next page by itself when the list is short enough to reach its end', () => {
    const onLoadMore = vi.fn()
    render(
      <VirtualRows
        label="Short"
        items={rows(4)}
        total={50}
        hasMore
        loadingMore={false}
        onLoadMore={onLoadMore}
        getKey={(r) => r.id}
        renderRow={(r) => <span>{r.name}</span>}
      />,
    )
    expect(onLoadMore).toHaveBeenCalled()
  })

  it('does not ask again while a page is loading or when there is no more', () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(
      <VirtualRows label="x" items={rows(4)} total={50} hasMore loadingMore onLoadMore={onLoadMore} getKey={(r) => r.id} renderRow={(r) => <span>{r.name}</span>} />,
    )
    rerender(<VirtualRows label="x" items={rows(4)} total={4} hasMore={false} loadingMore={false} onLoadMore={onLoadMore} getKey={(r) => r.id} renderRow={(r) => <span>{r.name}</span>} />)
    expect(onLoadMore).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })
})
