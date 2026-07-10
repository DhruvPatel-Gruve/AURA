import { cn } from '@/utils/cn'

interface Props {
  value:      number   // 0–100
  size?:      'sm' | 'md'
  color?:     'accent' | 'emerald' | 'amber' | 'red'
  className?: string
}

const colorMap = {
  accent:  'bg-accent',
  emerald: 'bg-emerald-600 dark:bg-emerald-400',
  amber:   'bg-amber-600 dark:bg-amber-400',
  red:     'bg-red-600 dark:bg-red-400',
}

const heightMap = { sm: 'h-1', md: 'h-2' }

export function ProgressBar({ value, size = 'md', color = 'accent', className }: Props) {
  const clamped = Math.min(100, Math.max(0, value))
  return (
    <div className={cn(
      'w-full bg-sunken ring-1 ring-inset ring-line rounded-full overflow-hidden',
      heightMap[size],
      className,
    )}>
      <div
        className={cn('h-full rounded-full transition-[width] duration-500', colorMap[color])}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}
