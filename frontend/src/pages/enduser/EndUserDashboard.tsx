import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { PlusCircle, CheckCircle, Clock, Hourglass } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { ticketsApi } from '@/api/tickets.api'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge } from '@/components/ui/Badge'
import type { BadgeTone } from '@/components/ui/Badge'
import { formatRelativeTime } from '@/utils/formatters'

const STATUS_TONES: Record<string, BadgeTone> = {
  resolved:  'success',
  reviewing: 'warn',
  open:      'neutral',
}

const STATUS_SPINES: Record<string, string> = {
  resolved:  'spine-agent',
  reviewing: 'spine-warn',
  open:      'spine-active',
}

/**
 * `status` may now be the real ITSM workflow status (e.g. "Open", "In
 * Progress", "Resolved") once AURA has synced it, or the older synthetic
 * open/reviewing/resolved fallback before that happens — bucket by keyword
 * so tone/spine/counts work either way.
 */
function normalizeStatus(status: string): 'open' | 'reviewing' | 'resolved' {
  const s = status.toLowerCase()
  if (s.includes('resolved') || s.includes('done') || s.includes('closed')) return 'resolved'
  if (s.includes('progress') || s.includes('review')) return 'reviewing'
  return 'open'
}

export default function EndUserDashboard() {
  const navigate        = useNavigate()
  const { displayName } = useAuthStore()

  const { data: myTickets, isLoading, isError, refetch } = useQuery({
    queryKey: ['tickets', 'mine'],
    queryFn:  ticketsApi.getMine,
    refetchInterval: 30_000,
  })

  const openCount     = myTickets?.filter((t) => normalizeStatus(t.status) !== 'resolved').length ?? 0
  const resolvedCount = myTickets?.filter((t) => normalizeStatus(t.status) === 'resolved').length ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        title="IT Support Portal"
        description={`Welcome${displayName ? `, ${displayName}` : ''}. How can we help you today?`}
      />

      {isError && <ErrorBanner message="Failed to load your tickets." onRetry={() => refetch()} />}

      {/* My tickets summary */}
      {myTickets && myTickets.length > 0 && (
        <div className="grid grid-cols-2 gap-4">
          <button onClick={() => navigate('/enduser/tickets?filter=open')} className="text-left">
            <StatCard label="Open Tickets" value={openCount} icon={Hourglass} className="transition-colors hover:border-faint/40" />
          </button>
          <button onClick={() => navigate('/enduser/tickets?filter=resolved')} className="text-left">
            <StatCard label="Resolved" value={resolvedCount} icon={CheckCircle} className="transition-colors hover:border-faint/40" />
          </button>
        </div>
      )}

      {/* Quick actions */}
      <div className="grid grid-cols-2 gap-4">
        <button
          onClick={() => navigate('/enduser/submit')}
          className="card p-6 text-left transition-colors hover:border-faint/40 group"
        >
          <p className="text-base font-semibold text-ink group-hover:text-accent transition-colors">
            Submit a Ticket
          </p>
          <p className="text-sm text-body mt-1">
            Report an IT issue or request support. AURA will triage and resolve it automatically when possible.
          </p>
          <span className="inline-block mt-4 text-xs font-medium text-accent group-hover:underline">
            Open form →
          </span>
        </button>

        <button
          onClick={() => navigate('/enduser/chat')}
          className="card p-6 text-left transition-colors hover:border-faint/40 group"
        >
          <p className="text-base font-semibold text-ink group-hover:text-accent transition-colors">
            Ask AURA
          </p>
          <p className="text-sm text-body mt-1">
            Get instant answers to common IT questions from our AI assistant, grounded in resolved ticket history.
          </p>
          <span className="inline-block mt-4 text-xs font-medium text-accent group-hover:underline">
            Start chat →
          </span>
        </button>
      </div>

      {/* My recent tickets */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="overline-label">My Recent Tickets</h2>
          {myTickets && myTickets.length > 0 && (
            <button onClick={() => navigate('/enduser/tickets')} className="text-xs text-accent hover:underline">
              See all
            </button>
          )}
        </div>
        {isLoading ? (
          <div className="flex justify-center py-6"><LoadingSpinner size="md" /></div>
        ) : myTickets && myTickets.length > 0 ? (
          <div className="space-y-2">
            {myTickets.slice(0, 5).map((t) => (
              <div
                key={t.ticket_id}
                className={`flex items-center justify-between py-2.5 pl-3 border-b border-line last:border-b-0 ${STATUS_SPINES[normalizeStatus(t.status)]}`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="min-w-0">
                    <p className="text-sm font-mono text-body truncate">{t.ticket_id}</p>
                    <p className="text-xs text-faint">
                      Submitted <span className="font-mono">{formatRelativeTime(t.submitted_at)}</span>
                    </p>
                  </div>
                </div>
                <Badge tone={STATUS_TONES[normalizeStatus(t.status)]} dot className="shrink-0">
                  {t.status}
                </Badge>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-faint py-2">
            You haven't submitted any tickets yet.
          </p>
        )}
      </div>

      {/* How it works */}
      <div className="card p-5">
        <h2 className="overline-label mb-4">How AURA Works</h2>
        <ol className="space-y-4">
          {[
            {
              icon: PlusCircle,
              title: 'Submit your ticket',
              detail: 'Describe your issue with as much detail as possible. AURA reads your request in seconds.',
            },
            {
              icon: CheckCircle,
              title: 'AURA triages automatically',
              detail: 'For common issues, AURA posts a resolution directly to your ticket — no waiting.',
            },
            {
              icon: Clock,
              title: 'Technician review when needed',
              detail: 'If AURA is uncertain, a technician reviews and approves the suggested resolution before it reaches you.',
            },
          ].map(({ icon: Icon, title, detail }) => (
            <li key={title} className="flex gap-4">
              <Icon className="h-4 w-4 text-faint shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-ink">{title}</p>
                <p className="text-xs text-body mt-0.5">{detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>

    </div>
  )
}
