import { Badge, type BadgeTone } from './Badge'

interface Props {
  score:      number | null | undefined
  className?: string
}

export function ConfidenceScoreBadge({ score, className }: Props) {
  if (score == null) return null
  const pct = Math.round(score * 100)
  const tone: BadgeTone = pct >= 90 ? 'success' : pct >= 70 ? 'warn' : 'critical'

  return (
    <Badge tone={tone} mono className={className}>
      {score.toFixed(2)}
    </Badge>
  )
}
