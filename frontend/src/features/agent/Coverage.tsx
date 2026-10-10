import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { AgentSection } from './types'

function SectionCoverage({ section }: { section: AgentSection }) {
  const [open, setOpen] = useState(false)
  const c = section.coverage
  const panelId = `coverage-${section.id}`
  const Icon = open ? ChevronDown : ChevronRight
  return (
    <li className="py-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded text-left text-sm font-medium text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {section.label}
      </button>
      {open && (
        <div id={panelId} className="mt-2 space-y-3 pl-6 text-sm">
          {!c ? (
            <p className="text-muted">No coverage report for this section yet.</p>
          ) : (
            <>
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Files read</h4>
                {c.files_read.length === 0 ? (
                  <p className="text-muted">No files read.</p>
                ) : (
                  <ul>
                    {c.files_read.map((f) => (
                      <li key={f.file_id} className="text-ink">
                        {f.path}
                        <span className="text-muted">
                          {f.pages.length > 0 ? ` (pages ${f.pages.join(', ')})` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Found but not read</h4>
                {c.found_not_read.length === 0 ? (
                  <p className="text-muted">None.</p>
                ) : (
                  <ul>
                    {c.found_not_read.map((f) => (
                      <li key={f.file_id} className="text-ink">
                        {f.path}
                        {f.why_not_read && <span className="text-muted"> -- not read: {f.why_not_read}</span>}
                        {f.why_found && <span className="block text-xs text-muted">Found because: {f.why_found}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="text-ink">
                {c.lines_without_proposal.length} of {c.lines_total} lines without a proposal.{' '}
                {c.lines_cost_source_only} priced from a cost source only.
              </p>
            </>
          )}
        </div>
      )}
    </li>
  )
}

export function Coverage({ sections }: { sections: AgentSection[] }) {
  return (
    <section aria-labelledby="agent-coverage-h" className="rounded-card bg-white p-5">
      <h2 id="agent-coverage-h" className="text-section font-semibold text-ink-title">
        Coverage
      </h2>
      {sections.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Coverage appears once sections have been read.</p>
      ) : (
        <ul className="mt-2 divide-y divide-hairline">
          {sections.map((s) => (
            <SectionCoverage key={s.id} section={s} />
          ))}
        </ul>
      )}
    </section>
  )
}
