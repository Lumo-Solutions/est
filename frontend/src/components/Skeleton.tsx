// docs/ui-design-system.md section 4.10 -- for the pages with the
// slowest/most jarring loading-to-content transition (big grids, project
// detail, settlement cockpit). Not a mechanical replacement of every
// "Loading..." in the app -- several are near-instantaneous and a
// skeleton would just flicker.
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 motion-reduce:animate-none ${className}`} />
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  )
}
