import { Badge, type BadgeTone } from './Badge'

const TONE: Record<string, BadgeTone> = {
  CRITICAL: 'critical',
  HIGH:     'warn',
  MEDIUM:   'info',
  LOW:      'neutral',
}

interface Props {
  priority:   string | null | undefined
  className?: string
}

export function PriorityBadge({ priority, className }: Props) {
  const key = (priority ?? 'LOW').toUpperCase()
  return (
    <Badge tone={TONE[key] ?? 'neutral'} dot className={className}>
      {key}
    </Badge>
  )
}
