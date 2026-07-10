import { apiClient } from '../api/client'

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

interface LogContext {
  [key: string]: unknown
}

const CONSOLE_METHOD: Record<LogLevel, 'debug' | 'info' | 'warn' | 'error'> = {
  debug: 'debug',
  info: 'info',
  warn: 'warn',
  error: 'error',
}

/**
 * Ships a log entry to the backend, which appends it to its own
 * logs/frontend.log (separate from the backend's logs/backend.log). Fire
 * and forget — a failed log shipment must never throw or recurse into
 * itself, or a logging outage would take down whatever called it.
 */
function ship(level: LogLevel, message: string, context?: LogContext, stack?: string) {
  apiClient
    .post('/logs/frontend', {
      level,
      message,
      context,
      stack,
      url: window.location.href,
      timestamp: new Date().toISOString(),
    })
    .catch(() => {
      /* swallow — logging must never surface its own errors to the user */
    })
}

function log(level: LogLevel, message: string, context?: LogContext) {
  // eslint-disable-next-line no-console
  console[CONSOLE_METHOD[level]](`[AURA] ${message}`, context ?? '')
  ship(level, message, context)
}

export const logger = {
  debug: (message: string, context?: LogContext) => log('debug', message, context),
  info: (message: string, context?: LogContext) => log('info', message, context),
  warn: (message: string, context?: LogContext) => log('warn', message, context),
  error: (message: string, error?: unknown, context?: LogContext) => {
    const stack = error instanceof Error ? error.stack : undefined
    const detail = error instanceof Error ? error.message : error ? String(error) : undefined
    // eslint-disable-next-line no-console
    console.error(`[AURA] ${message}`, error ?? '', context ?? '')
    ship('error', detail ? `${message}: ${detail}` : message, context, stack)
  },
}

/** Catches errors that never touch React (async callbacks, timers, addEventListener). */
export function installGlobalErrorLogging() {
  window.addEventListener('error', (event) => {
    logger.error('window.onerror', event.error ?? event.message)
  })
  window.addEventListener('unhandledrejection', (event) => {
    logger.error('unhandledrejection', event.reason)
  })
}
