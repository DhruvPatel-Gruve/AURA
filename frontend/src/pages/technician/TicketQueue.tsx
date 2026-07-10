import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Inbox, AlertCircle, ChevronDown, ChevronUp, Check, ChevronLeft, ChevronRight, Search,
} from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import { useAuthStore } from '@/store/authStore'
import type { LowConfQueueEntry, TicketSummary } from '@/api/types'
import { StatCard } from '@/components/ui/StatCard'
import { ConfidenceScoreBadge } from '@/components/ui/ConfidenceScoreBadge'
import { PriorityBadge } from '@/components/ui/PriorityBadge'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { AutonomyBadge } from '@/components/ui/AutonomyBadge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { humanize } from '@/utils/formatters'
import { cn } from '@/utils/cn'
import { TicketDetailPanel } from './components/TicketDetailPanel'

type ScopeTab = 'assigned' | 'all-teams'

const PAGE_SIZE = 20

// Spine class per row state: abstained → critical,
// SLA warning/breach override, else auto-resolved success.
function rowSpine(item: { abstained: boolean; sla_status: string | null }) {
  if (item.abstained) return 'spine-critical'
  if (item.sla_status === 'breached') return 'spine-critical'
  if (item.sla_status === 'warning') return 'spine-warn'
  return 'spine-agent'
}

function TicketsTable({
  items,
  total,
  page,
  setPage,
  expandedId,
  setExpandedId,
  queueByTicket,
  myTeamId,
}: {
  items: TicketSummary[]
  total: number
  page: number
  setPage: (updater: (p: number) => number) => void
  expandedId: string | null
  setExpandedId: (id: string | null) => void
  queueByTicket: Map<string, LowConfQueueEntry>
  myTeamId: string | null
}) {
  const pages = Math.ceil(total / PAGE_SIZE)
  const toggle = (id: string) => setExpandedId(id)

  return (
    <>
      <div className="card overflow-hidden">
        <div className="grid grid-cols-[2fr_1fr_1.2fr_1fr_1fr_1fr_1.2fr] gap-3 px-4 py-2 bg-sunken border-b border-line text-overline font-medium text-body uppercase">
          <span>Ticket ID</span>
          <span>Status</span>
          <span>Action</span>
          <span>Category</span>
          <span>Priority</span>
          <span>Auto Comment</span>
          <span>Confidence</span>
        </div>

        {items.length === 0 ? (
          <div className="text-center py-16">
            <Inbox className="h-10 w-10 text-line mx-auto mb-3" />
            <p className="text-sm text-faint">No tickets processed yet</p>
          </div>
        ) : (
          <div className="divide-y divide-line">
            {items.map((item) => {
              const pendingReview = queueByTicket.get(item.ticket_id)
              const expanded = expandedId === item.ticket_id
              return (
                <div key={item.ticket_id} className="overflow-hidden">
                  <button
                    onClick={() => toggle(expanded ? '' : item.ticket_id)}
                    className={cn(
                      'w-full grid grid-cols-[2fr_1fr_1.2fr_1fr_1fr_1fr_1.2fr] gap-3 px-4 py-3 hover:bg-sunken transition-colors text-left items-center',
                      rowSpine(item),
                    )}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {item.abstained
                        ? <AlertCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />
                        : <Check className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                      }
                      <span className="font-mono text-xs text-body truncate">{item.ticket_id}</span>
                      {pendingReview && <Badge tone="warn" dot>Needs Review</Badge>}
                      {item.team_id && myTeamId && item.team_id !== myTeamId && (
                        <Badge tone="neutral">Other Team</Badge>
                      )}
                      {expanded
                        ? <ChevronUp className="h-3.5 w-3.5 text-faint shrink-0 ml-auto" />
                        : <ChevronDown className="h-3.5 w-3.5 text-faint shrink-0 ml-auto" />
                      }
                    </div>
                    <span>
                      <StatusBadge status={item.status} />
                    </span>
                    <span className="text-xs text-body truncate">
                      {humanize(item.action_taken)}
                    </span>
                    <span className="text-xs text-body truncate">{item.category ?? '—'}</span>
                    <span>
                      {item.priority ? <PriorityBadge priority={item.priority} /> : <span className="text-xs text-faint">—</span>}
                    </span>
                    <span>
                      {item.auto_comment_enabled !== null ? <AutonomyBadge enabled={item.auto_comment_enabled} /> : <span className="text-xs text-faint">—</span>}
                    </span>
                    <span>
                      <ConfidenceScoreBadge score={item.confidence_score} />
                    </span>
                  </button>

                  {expanded && (
                    <TicketDetailPanel
                      ticketId={item.ticket_id}
                      queueEntry={pendingReview}
                      onClose={() => setExpandedId(null)}
                    />
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-faint font-mono tabular-nums">
            {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
          </p>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="btn-ghost !p-1.5 disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-xs text-body px-2 font-mono tabular-nums">
              {page} / {pages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page === pages}
              className="btn-ghost !p-1.5 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </>
  )
}

export default function TicketQueue() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scope = (searchParams.get('scope') === 'all-teams' ? 'all-teams' : 'assigned') as ScopeTab
  const myTeamId = useAuthStore((s) => s.teamId)
  const teamFilter = scope === 'assigned' ? (myTeamId ?? undefined) : undefined

  const [page, setPage]             = useState(1)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const [ticketSearch, setTicketSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['technician', 'ticket-list', page, ticketSearch, statusFilter, actionFilter, teamFilter],
    queryFn:  () => ticketsApi.list({
      page, page_size: PAGE_SIZE,
      ticket_id: ticketSearch || undefined,
      status: statusFilter || undefined,
      action_taken: actionFilter || undefined,
      team_id: teamFilter,
    }),
    refetchInterval: 60_000,
  })

  const { data: queue } = useQuery({
    queryKey: ['technician', 'queue-lcq', teamFilter],
    queryFn:  () => ticketsApi.getQueue({ team_id: teamFilter }),
    refetchInterval: 30_000,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const queueItems = queue ?? []
  const queueByTicket = new Map(queueItems.map((q) => [q.ticket_id, q]))

  // Accumulate filter option lists across pages instead of deriving them
  // from the currently-filtered result, which would shrink the dropdowns
  // as soon as any filter narrows the set.
  const [knownStatuses, setKnownStatuses] = useState<string[]>([])
  const [knownActions, setKnownActions]   = useState<string[]>([])
  useEffect(() => {
    if (data) {
      setKnownStatuses((prev) => Array.from(new Set([...prev, ...items.map((i) => i.status).filter((v): v is string => !!v)])).sort())
      setKnownActions((prev) => Array.from(new Set([...prev, ...items.map((i) => i.action_taken).filter((v): v is string => !!v)])).sort())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const setScope = (next: ScopeTab) => {
    setExpandedId(null)
    setPage(1)
    setSearchParams(next === 'assigned' ? {} : { scope: next })
  }

  const hasActiveFilters = !!(ticketSearch || statusFilter || actionFilter)

  return (
    <div className="space-y-5">
      <PageHeader
        title="Tickets"
        description="Every ticket AURA has touched — acknowledge assignment and review its suggestion in one place"
      />

      <div className="grid grid-cols-2 gap-4">
        <StatCard label="Total Processed" value={total.toLocaleString()} icon={Inbox} />
        <StatCard
          label="Awaiting Review"
          value={queueItems.length}
          delta={{ label: 'need your action', positive: queueItems.length === 0 }}
        />
      </div>

      {/* Scope tabs — which teams' tickets are in view */}
      <div className="flex gap-1 p-1 bg-sunken rounded-lg w-fit">
        {(['assigned', 'all-teams'] as ScopeTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setScope(tab)}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
              scope === tab
                ? 'bg-surface text-ink shadow-sm'
                : 'text-faint hover:text-body',
            )}
          >
            {tab === 'assigned' ? 'Assigned Tickets' : 'All Tickets'}
          </button>
        ))}
      </div>
      {scope === 'all-teams' && (
        <p className="text-xs text-faint -mt-3">
          Showing every team's tickets — you can only approve, edit, or reject items assigned to your own team.
        </p>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
          <input
            type="text"
            value={ticketSearch}
            onChange={(e) => { setPage(1); setTicketSearch(e.target.value) }}
            placeholder="Search ticket ID…"
            className="input-base pl-8 w-44 text-sm"
          />
        </div>
        <select value={statusFilter} onChange={(e) => { setPage(1); setStatusFilter(e.target.value) }} className="input-base w-40 text-sm">
          <option value="">All statuses</option>
          {knownStatuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={actionFilter} onChange={(e) => { setPage(1); setActionFilter(e.target.value) }} className="input-base w-44 text-sm">
          <option value="">All actions</option>
          {knownActions.map((a) => <option key={a} value={a}>{humanize(a)}</option>)}
        </select>
        {hasActiveFilters && (
          <button
            onClick={() => { setTicketSearch(''); setStatusFilter(''); setActionFilter(''); setPage(1) }}
            className="text-xs text-accent hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <TicketsTable
          items={items}
          total={total}
          page={page}
          setPage={setPage}
          expandedId={expandedId}
          setExpandedId={setExpandedId}
          queueByTicket={queueByTicket}
          myTeamId={myTeamId}
        />
      )}
    </div>
  )
}
