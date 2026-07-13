import { useEffect, useRef, useState } from 'react'
import { Bell, Sun, Moon, LogOut, CheckCheck, X } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useConfigStore } from '@/store/configStore'
import { useAuthStore } from '@/store/authStore'
import { useNotificationStore } from '@/store/notificationStore'
import { cn } from '@/utils/cn'

const EVENT_LABELS: Record<string, string> = {
  KILL_SWITCH_ACTIVATED:   'Kill switch',
  KILL_SWITCH_DEACTIVATED: 'Kill switch',
  TICKET_ASSIGNED:         'Ticket assigned',
  TICKET_UPDATED:          'Ticket updated',
  TICKET_REASSIGNED:       'Reassigned',
  ASSIGNMENT_OVERDUE:      'Assignment overdue',
  AURA_COMMENT_POSTED:     'AURA resolution',
  LOW_CONFIDENCE_QUEUED:   'Queued for review',
  ABSTENTION_FLAGGED:      'Abstention',
  SLA_WARNING:             'SLA warning',
  SLA_BREACHED:            'SLA breached',
  INGESTION_COMPLETE:      'Ingestion complete',
}

/* Spine tone per event class — state encoded by the system's one motif */
const EVENT_TONE: Record<string, string> = {
  KILL_SWITCH_ACTIVATED:   'bg-red-600',
  KILL_SWITCH_DEACTIVATED: 'bg-emerald-600',
  SLA_BREACHED:            'bg-red-600',
  SLA_WARNING:             'bg-amber-500',
  ASSIGNMENT_OVERDUE:      'bg-amber-500',
  LOW_CONFIDENCE_QUEUED:   'bg-amber-500',
  ABSTENTION_FLAGGED:      'bg-amber-500',
  AURA_COMMENT_POSTED:     'bg-emerald-600',
  INGESTION_COMPLETE:      'bg-emerald-600',
}

function NotificationPanel({ onClose }: { onClose: () => void }) {
  const { notifications, unreadCount, markRead, markAllRead } = useNotificationStore()

  return (
    <div className="absolute right-0 top-11 w-80 z-50 card shadow-card-md overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-faint" />
          <span className="font-display text-sm font-semibold text-ink">Notifications</span>
          {unreadCount > 0 && (
            <span className="h-5 min-w-5 px-1 rounded-full bg-accent text-accent-fg text-[10px] font-bold flex items-center justify-center">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {unreadCount > 0 && (
            <button
              onClick={markAllRead}
              className="h-7 w-7 rounded-md flex items-center justify-center hover:bg-sunken transition-colors"
              title="Mark all as read"
            >
              <CheckCheck className="h-3.5 w-3.5 text-faint" />
            </button>
          )}
          <button
            onClick={onClose}
            className="h-7 w-7 rounded-md flex items-center justify-center hover:bg-sunken transition-colors"
          >
            <X className="h-3.5 w-3.5 text-faint" />
          </button>
        </div>
      </div>

      <div className="max-h-96 overflow-y-auto divide-y divide-line/60">
        {notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center px-4">
            <Bell className="h-8 w-8 text-line mb-2" />
            <p className="text-sm text-body">No notifications yet</p>
            <p className="text-xs text-faint mt-0.5">
              Events like SLA warnings, AURA comments, and queue updates will appear here.
            </p>
          </div>
        ) : (
          notifications.map((n) => (
            <button
              key={n.id}
              onClick={() => markRead(n.id)}
              className={cn(
                'w-full text-left px-4 py-3 flex gap-3 hover:bg-sunken transition-colors',
                !n.read && 'bg-accent/5',
              )}
            >
              <span className={cn(
                'mt-1 h-full min-h-[32px] w-[3px] rounded-full shrink-0',
                EVENT_TONE[n.event_type] ?? (n.read ? 'bg-line' : 'bg-accent'),
              )} />
              <div className="min-w-0">
                <p className="overline-label mb-0.5">
                  {EVENT_LABELS[n.event_type] ?? n.event_type}
                </p>
                <p className="text-sm text-ink leading-snug break-words">
                  {n.message}
                </p>
                <p className="font-mono text-[11px] text-faint mt-1">
                  {new Date(n.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

export function TopBar() {
  const { logout }                                  = useAuth()
  const { theme, setTheme, killSwitchActive,
          companyName, companyLogo }                = useConfigStore()
  const { role }                                    = useAuthStore()
  const { unreadCount }                             = useNotificationStore()
  const showClientBranding = role !== 'master_admin' && (companyLogo || companyName)
  const [panelOpen, setPanelOpen]                   = useState(false)
  const panelRef                                    = useRef<HTMLDivElement>(null)

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark')

  useEffect(() => {
    if (!panelOpen) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setPanelOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [panelOpen])

  return (
    <header className="h-14 flex items-center justify-end px-4
                        bg-surface
                        border-b border-line shrink-0">

      {/* ── Right: client branding + controls ────────────────────────────── */}
      <div className="flex items-center gap-3">

        {/* Client company identity */}
        {showClientBranding && (
          <div className="flex items-center gap-2 pr-2 border-r border-line">
            {companyLogo && (
              <img
                src={companyLogo}
                alt={companyName || 'Company logo'}
                className="h-7 w-auto max-w-[100px] object-contain"
              />
            )}
            {companyName && (
              <span className="text-sm font-medium text-body hidden sm:block truncate max-w-[140px]">
                {companyName}
              </span>
            )}
          </div>
        )}

        {/* Kill switch status — mono, instrument-style */}
        {killSwitchActive && (
          <span className="inline-flex items-center gap-1.5 rounded
                            bg-red-50 dark:bg-red-900/25 text-red-700 dark:text-red-400
                            ring-1 ring-inset ring-red-200 dark:ring-red-800
                            px-2 h-6 font-mono text-[11px] font-medium tracking-wide">
            <span className="h-1.5 w-1.5 rounded-full bg-red-600 animate-pulse" />
            SUSPENDED
          </span>
        )}

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="btn-ghost h-8 w-8 p-0"
          aria-label="Toggle theme"
        >
          {theme === 'dark'
            ? <Sun  className="h-4 w-4" />
            : <Moon className="h-4 w-4" />
          }
        </button>

        {/* Notification bell */}
        <div className="relative" ref={panelRef}>
          <button
            className="btn-ghost h-8 w-8 p-0 relative"
            aria-label="Notifications"
            onClick={() => setPanelOpen((o) => !o)}
          >
            <Bell className="h-4 w-4" />
            {unreadCount > 0 && (
              <span className={cn(
                'absolute -top-0.5 -right-0.5',
                'h-4 w-4 rounded-full text-[10px] font-bold',
                'bg-accent text-accent-fg',
                'flex items-center justify-center',
              )}>
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </button>
          {panelOpen && <NotificationPanel onClose={() => setPanelOpen(false)} />}
        </div>

        {/* Logout */}
        <button
          onClick={logout}
          className="btn-ghost h-8 w-8 p-0 text-faint hover:text-red-600"
          aria-label="Log out"
        >
          <LogOut className="h-4 w-4" />
        </button>

      </div>
    </header>
  )
}
