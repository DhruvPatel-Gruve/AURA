import { cn } from '@/utils/cn'

interface Props {
  score:      number | null | undefined   // 0–1
  className?: string
}

/**
 * Confidence as instrumentation: mono value + 32px meter bar.
 * A number with a physical representation reads as a measurement,
 * not a marketing claim.
 */
export function ConfidenceMeter({ score, className }: Props) {
  if (score == null) return null
  const pct = Math.min(100, Math.max(0, score * 100))
  const fill =
    pct >= 90 ? 'bg-emerald-600 dark:bg-emerald-400'
    : pct >= 70 ? 'bg-amber-600 dark:bg-amber-400'
    : 'bg-red-600 dark:bg-red-400'

  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span className="w-8 h-1 rounded-full bg-sunken overflow-hidden ring-1 ring-inset ring-line">
        <span className={cn('block h-full rounded-full', fill)} style={{ width: `${pct}%` }} />
      </span>
      <span className="font-mono text-xs text-ink tabular-nums">{score.toFixed(2)}</span>
    </span>
  )
}
