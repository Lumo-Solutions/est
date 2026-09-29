import { PageTitle } from '../components/PageTitle'

export function PlaceholderPage({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="p-6">
      <PageTitle>{title}</PageTitle>
      <p className="mt-2 text-sm text-slate-500">This screen lands in {phase}.</p>
    </div>
  )
}
