import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'
import { TabBar } from './TabBar'
import { Pagination } from './Pagination'
import { TextField } from './Field'
import { initialsOf } from '../lib/initials'

describe('Button', () => {
  it('forwards disabled + title so SoD-disabled buttons keep their explanation', () => {
    const onClick = vi.fn()
    render(
      <Button disabled title="Awaiting a different approver" onClick={onClick}>
        Approve
      </Button>,
    )
    const btn = screen.getByRole('button', { name: 'Approve' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'Awaiting a different approver')
    fireEvent.click(btn)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('loading disables the button and defaults to type=button', () => {
    render(<Button loading>Save</Button>)
    const btn = screen.getByRole('button', { name: 'Save' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('type', 'button')
  })
})

describe('TabBar', () => {
  function Harness() {
    const [v, setV] = useState('a')
    return (
      <TabBar
        label="Sections"
        idPrefix="t"
        value={v}
        onChange={setV}
        tabs={[
          { id: 'a', label: 'Alpha' },
          { id: 'b', label: 'Beta' },
          { id: 'c', label: 'Gamma' },
        ]}
      />
    )
  }

  it('exposes tab roles by name with roving tabindex', () => {
    render(<Harness />)
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute('tabindex', '-1')
  })

  it('arrow keys, Home and End move selection and wrap', () => {
    render(<Harness />)
    const alpha = screen.getByRole('tab', { name: 'Alpha' })
    fireEvent.keyDown(alpha, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Beta' }), { key: 'End' })
    expect(screen.getByRole('tab', { name: 'Gamma' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Gamma' }), { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('Pagination', () => {
  it('renders nothing for a single page', () => {
    const { container } = render(<Pagination page={1} pageCount={1} onPageChange={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('marks the current page and disables Previous on page 1', () => {
    const onChange = vi.fn()
    render(<Pagination page={1} pageCount={3} onPageChange={onChange} />)
    expect(screen.getByRole('button', { name: 'Page 1' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: /Previous/ })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /Next/ }))
    expect(onChange).toHaveBeenCalledWith(2)
  })
})

describe('TextField', () => {
  it('associates a real label and announces errors', () => {
    render(<TextField label="Project code" error="Required" />)
    const input = screen.getByLabelText('Project code')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
  })
})

describe('initialsOf', () => {
  it.each([
    ['md.abdullah', 'MA'],
    ['estimator1', 'ES'],
    ['Jane Q Public', 'JP'],
    ['   ', '?'],
  ])('%s -> %s', (name, expected) => {
    expect(initialsOf(name)).toBe(expected)
  })
})
