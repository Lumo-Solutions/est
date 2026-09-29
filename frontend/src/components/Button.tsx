import type { ButtonHTMLAttributes } from 'react'
import { Spinner } from './Spinner'

// docs/figma-implementation-plan.md 3.2 -- Figma "Save"/"Send" (solid, 15px
// radius) and "Repay"/"Download" (outlined pill). The three variants are the
// ones docs/ui-design-system.md 4.2 already defined; only their shape/colour
// tokens changed. Everything a caller passes (disabled, title, aria-*,
// onClick, type) is forwarded untouched -- SoD's "Awaiting a different
// approver" disabled+title Approve/Reject buttons depend on that.
export type ButtonVariant = 'primary' | 'secondary' | 'destructive'
export type ButtonSize = 'md' | 'sm'

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'rounded-control bg-brand text-white hover:bg-brand-hover',
  secondary: 'rounded-pill border border-brand text-brand hover:bg-brand-subtle',
  destructive: 'rounded-pill border border-red-700 text-red-700 hover:bg-danger-subtle',
}

const SIZE: Record<ButtonSize, string> = {
  md: 'px-6 py-2.5 text-base',
  sm: 'px-4 py-1.5 text-sm',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  // Shows the shared Spinner (design-system 4.2) and disables the button.
  loading?: boolean
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  type = 'button',
  disabled,
  className = '',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}
