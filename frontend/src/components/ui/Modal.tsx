import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/utils/cn'

interface Props {
  open:      boolean
  onClose:   () => void
  title:     string
  children:  React.ReactNode
  className?: string
  size?:     'sm' | 'md' | 'lg'
}

const sizeMap = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-2xl' }

export function Modal({ open, onClose, title, children, className, size = 'md' }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => { if (e.target === overlayRef.current) onClose() }}
    >
      <div className={cn('card w-full shadow-card-md', sizeMap[size], className)}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line">
          <h2 className="font-display text-sm font-semibold text-ink">{title}</h2>
          <button onClick={onClose} className="btn-ghost !p-1 rounded-md">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}
