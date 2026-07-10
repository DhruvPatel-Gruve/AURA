import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Inbox, List, AlertCircle, CheckCircle } from 'lucide-react'
import { dashboardApi } from '@/api/dashboard.api'
import { ticketsApi } from '@/api/tickets.api'
import { StatCard } from '@/components/ui/StatCard'
import { ConfidenceScoreBadge } from '@/components/ui/ConfidenceScoreBadge'
import { PriorityBadge } from '@/components/ui/PriorityBadge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge } from '@/components/ui/Badge'
import type { BadgeTone } from '@/components/ui/Badge'
import { humanize } from '@/utils/formatters'

const SLA_TONES: Record<string, BadgeTone> = {
  breached: 'critical',
  warning:  'warn',
  ok:       'success',
}

export default function TechnicianDashboard() {
  const navigate = useNavigate()

  const { data: stats, isLoading: statsLoading, isError: statsError, refetch: refetchStats } = useQuery({
    queryKey: ['technician', 'stats'],
    queryFn:  () => dashboardApi.getTechnicianStats(),
    refetchInterval: 30_000,
  })

  const { data: queue, isLoading: queueLoading, isError: queueError, refetch: refetchQueue } = useQuery({
    queryKey: ['technician', 'queue-lcq'],
    queryFn:  () => ticketsApi.getQueue(),
    refetchInterval: 30_000,
  })

  const { data: recentTickets, isLoading: ticketsLoading, isError: ticketsError, refetch: refetchTickets } = useQuery({
    queryKey: ['technician', 'ticket-list', 1],
    queryFn:  () => ticketsApi.list({ page: 1, page_size: 5 }),
    refetchInterval: 60_000,
  })

  const recentItems = recentTickets?.items ?? []
  const abstainedCount  = queue?.filter((i) => i.abstained).length ?? 0
  const lowConfCount    = queue?.filter((i) => !i.abstained).length ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        title="Technician Dashboard"
        description="Your queue, SLA alerts, and AURA suggestions needing review"
      />

      {statsError && <ErrorBanner message="Failed to load your stats." onRetry={() => refetchStats()} />}
      {queueError && <ErrorBanner message="Failed to load your queue." onRetry={() => refetchQueue()} />}
      {ticketsError && <ErrorBanner message="Failed to load recent tickets." onRetry={() => refetchTickets()} />}

      {statsLoading ? (
        <div className="flex justify-center py-12"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Total Pending"
              value={stats?.queue_count ?? 0}
              icon={Inbox}
              delta={{ label: 'unresolved items', positive: (stats?.queue_count ?? 0) === 0 }}
            />
            <StatCard
              label="Awaiting Review"
              value={stats?.low_conf_pending ?? 0}
              icon={List}
              delta={{ label: 'need your action', positive: (stats?.low_conf_pending ?? 0) === 0 }}
            />
            <StatCard
              label="SLA Breaches"
              value={stats?.sla_breach_count ?? 0}
              icon={AlertCircle}
              delta={{ label: 'all time', positive: (stats?.sla_breach_count ?? 0) === 0 }}
            />
          </div>

          {/* Quick breakdown */}
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => navigate('/technician/queue')}
              className="card p-5 text-left transition-colors hover:border-faint/40 group"
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="overline-label">Tickets</h2>
                <span className="text-xs text-accent font-medium group-hover:underline">View all →</span>
              </div>
              <p className="text-2xl font-bold text-ink font-mono tabular-nums">
                {queueLoading ? '—' : queue?.length ?? 0}
              </p>
              <p className="text-xs text-faint mt-1">Items in ticket queue</p>
              <div className="flex gap-3 mt-3 text-xs text-body">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-amber-400" />
                  <span className="font-mono tabular-nums">{lowConfCount}</span> low confidence
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-red-400" />
                  <span className="font-mono tabular-nums">{abstainedCount}</span> abstained
                </span>
              </div>
            </button>

            <button
              onClick={() => navigate('/technician/queue?filter=needs-review')}
              className="card p-5 text-left transition-colors hover:border-faint/40 group"
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="overline-label">Needs Review</h2>
                <span className="text-xs text-accent font-medium group-hover:underline">Review →</span>
              </div>
              <p className="text-2xl font-bold text-ink font-mono tabular-nums">
                {queueLoading ? '—' : lowConfCount}
              </p>
              <p className="text-xs text-faint mt-1">Low-confidence suggestions to approve</p>
              <p className="text-xs text-faint mt-3">
                Acknowledge and review, edit, or reject AURA's draft replies — all from the same row
              </p>
            </button>
          </div>

          {/* Recent processed tickets */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="overline-label">Recently Processed Tickets</h2>
              <button
                onClick={() => navigate('/technician/queue')}
                className="text-xs text-accent hover:underline"
              >
                See all
              </button>
            </div>
            {ticketsLoading ? (
              <LoadingSpinner size="md" />
            ) : recentItems.length ? (
              <div className="space-y-2">
                {recentItems.map((item) => (
                  <div
                    key={item.ticket_id}
                    className={`flex items-center justify-between py-2.5 pl-3 border-b border-line last:border-b-0 ${
                      item.abstained ? 'spine-critical' : 'spine-agent'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div>
                        <p className="text-sm font-mono text-body">{item.ticket_id}</p>
                        <p className="text-xs text-faint">
                          {humanize(item.action_taken)} · {item.category ?? 'Uncategorised'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {item.claimed_by && (
                        <span title={`Claimed by ${item.claimed_by}`}>
                          <Badge tone="neutral">Claimed</Badge>
                        </span>
                      )}
                      {item.sla_status && (
                        <span title={item.sla_deadline ? `SLA deadline: ${item.sla_deadline}` : undefined}>
                          <Badge tone={SLA_TONES[item.sla_status] ?? 'neutral'} dot>{humanize(item.sla_status)}</Badge>
                        </span>
                      )}
                      {item.priority && <PriorityBadge priority={item.priority} />}
                      <ConfidenceScoreBadge score={item.confidence_score} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <CheckCircle className="h-10 w-10 text-line mx-auto mb-2" />
                <p className="text-sm font-medium text-body">No tickets processed yet</p>
                <p className="text-xs text-faint mt-1">Tickets will appear here once AURA processes them</p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
