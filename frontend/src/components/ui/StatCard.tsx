import { cn } from '@/utils/cn'
import type { LucideIcon } from 'lucide-react'

interface Props {
  label:     string
  value:     string | number
  delta?:    { label: string; positive: boolean }
  icon?:     LucideIcon   // accepted for API compat; intentionally not rendered
  loading?:  boolean
  className?: string
}

/**
 * Stat tile: overline label, display-face tabular number, mono delta.
 * No icon box — a number that stands on its own reads as instrumentation.
 */
export function StatCard({ label, value, delta, loading, className }: Props) {
  return (
    <div className={cn('card p-5', className)}>
      <p className="overline-label">{label}</p>
      {loading ? (
        <div className="mt-2 h-8 w-24 skeleton" />
      ) : (
        <p className="mt-1.5 font-display text-2xl font-semibold text-ink tabular-nums leading-8">
          {value}
        </p>
      )}
      {delta && !loading && (
        <p className={cn(
          'mt-1 font-mono text-xs tabular-nums',
          delta.positive ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400',
        )}>
          {delta.label}
        </p>
      )}
    </div>
  )
}
