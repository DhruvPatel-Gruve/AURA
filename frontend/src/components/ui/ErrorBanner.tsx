import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  message?:  string
  onRetry?:  () => void
  className?: string
}

export function ErrorBanner({ message = 'Failed to load data.', onRetry, className }: Props) {
  return (
    <div className={`flex items-center justify-between gap-3 rounded-md spine-critical
                      bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/40
                      px-4 py-3 ${className ?? ''}`}>
      <div className="flex items-center gap-2 text-sm text-red-700 dark:text-red-400">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>{message}</span>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1 text-xs font-medium text-red-700 dark:text-red-400 hover:underline shrink-0"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </button>
      )}
    </div>
  )
}
