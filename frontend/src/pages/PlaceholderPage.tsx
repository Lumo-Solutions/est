export function PlaceholderPage({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">{title}</h1>
      <p className="mt-2 text-sm text-slate-500">This screen lands in {phase}.</p>
    </div>
  )
}
