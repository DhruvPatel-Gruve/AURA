import { cn } from '@/utils/cn'

export type BadgeTone = 'success' | 'warn' | 'critical' | 'info' | 'neutral' | 'accent'

/**
 * Unified badge primitive — every status chip in the app renders through this.
 * Tinted fill + ring, 20px tall, 11px medium. Never solid, never pill-round.
 */
const TONES: Record<BadgeTone, string> = {
  success:  'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-900/25 dark:text-emerald-400 dark:ring-emerald-800',
  warn:     'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-900/25 dark:text-amber-400 dark:ring-amber-800',
  critical: 'bg-red-50 text-red-700 ring-red-200 dark:bg-red-900/25 dark:text-red-400 dark:ring-red-800',
  info:     'bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-900/25 dark:text-blue-400 dark:ring-blue-800',
  neutral:  'bg-sunken text-body ring-line',
  accent:   'bg-accent-subtle text-accent ring-accent/25',
}

interface Props {
  tone:       BadgeTone
  children:   React.ReactNode
  dot?:       boolean
  mono?:      boolean          // for numeric content (scores, counts)
  className?: string
}

const DOT_COLOR: Record<BadgeTone, string> = {
  success:  'bg-emerald-600 dark:bg-emerald-400',
  warn:     'bg-amber-600 dark:bg-amber-400',
  critical: 'bg-red-600 dark:bg-red-400',
  info:     'bg-blue-600 dark:bg-blue-400',
  neutral:  'bg-faint',
  accent:   'bg-accent',
}

export function Badge({ tone, children, dot, mono, className }: Props) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 h-5 rounded px-1.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap',
      TONES[tone],
      mono && 'font-mono',
      className,
    )}>
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', DOT_COLOR[tone])} />}
      {children}
    </span>
  )
}
