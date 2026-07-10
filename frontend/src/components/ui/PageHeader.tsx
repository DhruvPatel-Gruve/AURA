import { cn } from '@/utils/cn'

interface Props {
  title:       string
  description?: string
  actions?:    React.ReactNode
  className?:  string
}

/**
 * Standard page header — identical structure on every page is what makes
 * twenty screens feel like one product.
 */
export function PageHeader({ title, description, actions, className }: Props) {
  return (
    <div className={cn('flex items-start justify-between gap-4 mb-5', className)}>
      <div className="min-w-0">
        <h1 className="font-display text-xl font-semibold text-ink leading-7">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-body">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  )
}
