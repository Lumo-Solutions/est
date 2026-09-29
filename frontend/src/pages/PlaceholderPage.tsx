import { PageTitle } from '../components/PageTitle'

export function PlaceholderPage({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>{title}</PageTitle>
      <p className="mt-2 text-sm text-muted">This screen lands in {phase}.</p>
    </div>
  )
}
