import { Badge } from './Badge'

interface Props {
  enabled:    boolean | null | undefined
  className?: string
}

export function AutonomyBadge({ enabled, className }: Props) {
  const isOn = !!enabled
  return (
    <Badge tone={isOn ? 'success' : 'neutral'} dot className={className}>
      {isOn ? 'AUTO' : 'MANUAL'}
    </Badge>
  )
}
