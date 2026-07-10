import { useEffect } from 'react'
import { CheckCircle2, Info, AlertTriangle, X } from 'lucide-react'
import { useToastStore, type Toast, type ToastVariant } from '@/store/toastStore'
import { cn } from '@/utils/cn'

const AUTO_DISMISS_MS = 6000

const ICONS: Record<ToastVariant, typeof Info> = {
  info:    Info,
  success: CheckCircle2,
  warning: AlertTriangle,
}

const STYLES: Record<ToastVariant, string> = {
  info:    'spine-active border-line bg-surface text-ink',
  success: 'spine-agent border-line bg-surface text-ink',
  warning: 'spine-warn border-line bg-surface text-ink',
}

const ICON_STYLES: Record<ToastVariant, string> = {
  info:    'text-blue-600 dark:text-blue-400',
  success: 'text-emerald-600 dark:text-emerald-400',
  warning: 'text-amber-600 dark:text-amber-400',
}

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss)
  const Icon = ICONS[toast.variant]

  useEffect(() => {
    const t = setTimeout(() => dismiss(toast.id), AUTO_DISMISS_MS)
    return () => clearTimeout(t)
  }, [toast.id, dismiss])

  return (
    <div className={cn(
      'flex items-start gap-2.5 rounded-md border px-4 py-3 shadow-card-md w-80 pointer-events-auto',
      STYLES[toast.variant],
    )}>
      <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', ICON_STYLES[toast.variant])} />
      <p className="text-sm flex-1">{toast.message}</p>
      <button onClick={() => dismiss(toast.id)} className="shrink-0 opacity-60 hover:opacity-100">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts)

  if (toasts.length === 0) return null

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => <ToastItem key={t.id} toast={t} />)}
    </div>
  )
}
