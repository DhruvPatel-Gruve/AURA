import { formatDistanceToNow, format, parseISO } from 'date-fns'

export function formatRelativeTime(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true })
  } catch {
    return iso
  }
}

export function formatDateTime(iso: string): string {
  try {
    return format(parseISO(iso), 'dd MMM yyyy, HH:mm')
  } catch {
    return iso
  }
}

// Turn a backend snake_case enum value into plain, readable text —
// "held_low_confidence" -> "Held Low Confidence".
export function humanize(value: string | null | undefined): string {
  if (!value) return '—'
  return value
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

// Convert hex color to CSS rgb triplet string
export function hexToRgbString(hex: string): string | null {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  if (!result) return null
  return `${parseInt(result[1], 16)} ${parseInt(result[2], 16)} ${parseInt(result[3], 16)}`
}

// Lighten a hex color toward white by a 0–1 factor
export function lightenHex(hex: string, factor: number): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  if (!result) return hex
  const lerp = (v: number) => Math.min(255, Math.round(v + (255 - v) * factor))
  const r = lerp(parseInt(result[1], 16))
  const g = lerp(parseInt(result[2], 16))
  const b = lerp(parseInt(result[3], 16))
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}
