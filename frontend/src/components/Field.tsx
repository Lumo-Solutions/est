import { useId } from 'react'
import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

// Figma forms: 16px label above a 15px-radius input. Border is
// --color-outline (3.3:1) not Figma's #DFEAF2 (1.22:1 -- fails WCAG 1.4.11).
// Every field renders a real <label htmlFor> (design-system 6) -- Figma's
// placeholder-only look is NOT reproduced.
export const controlClasses =
  'w-full rounded-control border border-outline bg-white px-4 py-2.5 text-[15px] text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand disabled:cursor-not-allowed disabled:bg-canvas disabled:opacity-70'

function FieldShell({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string
  label: string
  error?: string | null
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-base text-ink">
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-muted">{hint}</p>}
      {error && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}

interface Common {
  label: string
  error?: string | null
  hint?: string
}

export function TextField({
  label,
  error,
  hint,
  id: idProp,
  className = '',
  ...rest
}: Common & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId()
  const id = idProp ?? auto
  return (
    <FieldShell id={id} label={label} error={error} hint={hint}>
      <input id={id} aria-invalid={error ? true : undefined} className={`${controlClasses} ${className}`} {...rest} />
    </FieldShell>
  )
}

export function SelectField({
  label,
  error,
  hint,
  id: idProp,
  className = '',
  children,
  ...rest
}: Common & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId()
  const id = idProp ?? auto
  return (
    <FieldShell id={id} label={label} error={error} hint={hint}>
      <select id={id} aria-invalid={error ? true : undefined} className={`${controlClasses} ${className}`} {...rest}>
        {children}
      </select>
    </FieldShell>
  )
}

export function TextAreaField({
  label,
  error,
  hint,
  id: idProp,
  className = '',
  ...rest
}: Common & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId()
  const id = idProp ?? auto
  return (
    <FieldShell id={id} label={label} error={error} hint={hint}>
      <textarea id={id} aria-invalid={error ? true : undefined} className={`${controlClasses} ${className}`} {...rest} />
    </FieldShell>
  )
}
