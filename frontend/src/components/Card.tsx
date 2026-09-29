import type { ReactNode } from 'react'

// Figma: every panel is a white 25px-radius surface on the #F5F7FA canvas
// with no shadow (design-system 2.5: flat, level 0 -- matches the frames).
export function Card({ className = '', children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`rounded-card bg-white p-6 ${className}`} {...rest}>
      {children}
    </div>
  )
}

// Figma section headings are 22/600 navy with an optional trailing link
// ("See All"). `as` lets a page keep a correct heading outline: the page's
// <h1> is the title, section headings are <h2>.
export function SectionHeading({
  as: Tag = 'h2',
  action,
  children,
  className = '',
}: {
  as?: 'h2' | 'h3'
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`mb-3 flex items-baseline justify-between gap-4 ${className}`}>
      <Tag className="text-section font-semibold text-ink-title">{children}</Tag>
      {action}
    </div>
  )
}
