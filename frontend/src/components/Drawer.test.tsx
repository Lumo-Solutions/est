import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Drawer } from './Drawer'

function Harness({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open it</button>
      <Drawer
        open={open}
        title="Edit thing"
        onClose={() => {
          onClose?.()
          setOpen(false)
        }}
      >
        <input aria-label="Inside" />
      </Drawer>
    </>
  )
}

describe('Drawer', () => {
  it('renders nothing while closed and a labelled dialog when open', () => {
    render(<Harness />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open it' }))
    expect(screen.getByRole('dialog', { name: 'Edit thing' })).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByLabelText('Inside')).toBeInTheDocument()
  })

  it('moves focus into the panel, closes on Escape, Close and the backdrop, and gives focus back to the opener', () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    const opener = screen.getByRole('button', { name: 'Open it' })
    opener.focus()
    fireEvent.click(opener)
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    fireEvent.click(opener)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    fireEvent.click(opener)
    fireEvent.click(screen.getByRole('dialog').parentElement as HTMLElement) // the backdrop
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    fireEvent.click(opener)
    fireEvent.click(screen.getByLabelText('Inside')) // clicks inside do not dismiss
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
