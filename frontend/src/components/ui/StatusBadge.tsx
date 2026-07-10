import { Badge, type BadgeTone } from './Badge'

/**
 * Maps the live ITSM ticket status (whatever the connected provider's
 * workflow names its states — typically Open / In Progress / Resolved) to a
 * badge tone by keyword, since we display the raw status string rather than
 * a hardcoded enum.
 */
function toneFor(status: string): BadgeTone {
  const s = status.toLowerCase()
  if (s.includes('resolved') || s.includes('done') || s.includes('closed')) return 'success'
  if (s.includes('progress') || s.includes('review')) return 'warn'
  return 'info'
}

interface Props {
  status:     string | null | undefined
  className?: string
}

export function StatusBadge({ status, className }: Props) {
  if (!status) return <span className="text-xs text-faint">—</span>
  return (
    <Badge tone={toneFor(status)} dot className={className}>
      {status}
    </Badge>
  )
}
