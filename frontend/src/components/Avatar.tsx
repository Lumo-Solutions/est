import { initialsOf } from '../lib/initials'

// Header avatar. Figma uses a stock photo (a remote/licensed asset -- not
// allowed in an air-gapped build), so this is initials on a brand tint.
// Decorative: the adjacent username text is the accessible name.

export function Avatar({ name, className = '' }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-subtle text-sm font-semibold text-brand ${className}`}
    >
      {initialsOf(name)}
    </span>
  )
}
