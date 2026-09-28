import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DevMfaBanner } from './DevMfaBanner'

describe('DevMfaBanner', () => {
  it('shows the DEV: MFA disabled banner when the backend reports the bypass is active', () => {
    render(<DevMfaBanner active />)
    expect(screen.getByRole('status')).toHaveTextContent('DEV: MFA disabled')
  })

  it('renders nothing when MFA is on', () => {
    const { container } = render(<DevMfaBanner active={false} />)
    expect(container).toBeEmptyDOMElement()
  })
})
