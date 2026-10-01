import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const m = vi.hoisted(() => ({ roles: [] as string[] }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => m.roles.includes(x)) }),
}))
vi.mock('./api', () => ({
  useCostEstimate: () => ({
    data: {
      package_id: 'pk1', provider: 'qwen', external: true, ai_available: true, files_needing_ai: 3, models: [], total_usd: 0.5,
      any_unverified: false, monthly_remaining_usd: null, project_remaining_usd: null, within_budget: true,
      confirmation_required: true, confirmed_at: null, confirmed_usd: null, note: '',
    },
    isError: false,
  }),
  useConfirmCost: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { IntakeProgress } from './IntakeProgress'
import { packageProgress, treeSummary } from './testFixtures'

describe('IntakeProgress', () => {
  beforeEach(() => {
    m.roles = []
  })

  describe('waiting for the cost OK', () => {
    const waiting = [packageProgress({ status: 'processing', awaiting_cost_confirmation: true })]
    const text = 'Waiting for your OK on the estimated AI cost before reading starts'

    it('lead estimators see the banner and a button that opens the estimate', () => {
      m.roles = ['lead_estimator']
      render(<IntakeProgress summary={treeSummary({ total: 5 })} packages={waiting} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Review estimated cost' }))
      expect(screen.getByRole('dialog', { name: 'Estimated AI cost' })).toBeInTheDocument()
    })

    it('other roles see only the banner text', () => {
      m.roles = ['estimator']
      render(<IntakeProgress summary={treeSummary({ total: 5 })} packages={waiting} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Review estimated cost' })).not.toBeInTheDocument()
    })

    it('no banner when no pack is waiting', () => {
      m.roles = ['lead_estimator']
      render(<IntakeProgress summary={treeSummary({ total: 10 })} packages={[packageProgress({ status: 'paused' })]} />)
      expect(screen.queryByText(text)).not.toBeInTheDocument()
    })
  })

  it('renders nothing when nothing is happening', () => {
    const { container } = render(<IntakeProgress summary={treeSummary({ total: 5 })} packages={[packageProgress({ status: 'ready' })]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows Uploaded U of E files while bytes are still arriving', () => {
    render(
      <IntakeProgress
        summary={treeSummary({ total: 40, pending_upload: 60 })}
        packages={[packageProgress({ status: 'uploading', expected_count: 100, registered: 100, uploaded: 40, pending_upload: 60 })]}
      />,
    )
    expect(screen.getByText('Uploaded 40 of 100 files')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Files uploaded' })).toHaveAttribute('aria-valuenow', '40')
    expect(screen.queryByText(/This upload was not finished/)).not.toBeInTheDocument()
  })

  it('explains an upload that stopped half way and how to continue', () => {
    render(
      <IntakeProgress
        summary={treeSummary({ total: 30 })}
        packages={[packageProgress({ status: 'uploading', expected_count: 100, registered: 30, uploaded: 30, pending_upload: 0 })]}
      />,
    )
    expect(screen.getByText(/This upload was not finished \(30 of 100 files arrived\)\. Drop the same folder again under .Add more files. to continue\./)).toBeInTheDocument()
  })

  it('shows Reading documents D of T with the per-state counts, from the summary only', () => {
    render(<IntakeProgress summary={treeSummary({ total: 10, in_progress: 4, by_display_status: { reading: 3, queued: 1, ready: 6 } })} />)
    expect(screen.getByText('Reading documents: 6 of 10')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Documents read' })
    expect(bar).toHaveAttribute('aria-valuenow', '6')
    expect(bar).toHaveAttribute('aria-valuemax', '10')
    expect(screen.getByText(/Reading:/)).toBeInTheDocument()
    expect(screen.getByText(/Queued:/)).toBeInTheDocument()
  })

  it('says unpacking while a pack is processing and no file has arrived yet', () => {
    render(<IntakeProgress summary={treeSummary({ packages_processing: 1 })} />)
    expect(screen.getByText('Unpacking your upload...')).toBeInTheDocument()
  })

  it('shows a paused banner', () => {
    render(<IntakeProgress summary={treeSummary({ total: 10 })} packages={[packageProgress({ status: 'paused' })]} />)
    expect(screen.getByText(/This pack is paused/)).toBeInTheDocument()
  })
})
