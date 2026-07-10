import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Inbox, Search, PlusCircle } from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { Badge } from '@/components/ui/Badge'
import type { BadgeTone } from '@/components/ui/Badge'
import { ConfidenceScoreBadge } from '@/components/ui/ConfidenceScoreBadge'
import { formatRelativeTime, formatDateTime } from '@/utils/formatters'
import { cn } from '@/utils/cn'

const STATUS_TONES: Record<string, BadgeTone> = {
  resolved:  'success',
  reviewing: 'warn',
  open:      'neutral',
}

/**
 * `status` may be the real ITSM workflow status (e.g. "Open", "In
 * Progress", "Resolved") once AURA has synced it, or the older synthetic
 * open/reviewing/resolved fallback before that happens — bucket by keyword
 * so tone/filtering work either way.
 */
function normalizeStatus(status: string): 'open' | 'reviewing' | 'resolved' {
  const s = status.toLowerCase()
  if (s.includes('resolved') || s.includes('done') || s.includes('closed')) return 'resolved'
  if (s.includes('progress') || s.includes('review')) return 'reviewing'
  return 'open'
}

type FilterTab = 'all' | 'open' | 'resolved'

export default function MyTickets() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = (searchParams.get('filter') === 'open' || searchParams.get('filter') === 'resolved'
    ? searchParams.get('filter')
    : 'all') as FilterTab

  const [search, setSearch] = useState('')

  const { data: tickets, isLoading, isError, refetch } = useQuery({
    queryKey: ['tickets', 'mine'],
    queryFn:  ticketsApi.getMine,
    refetchInterval: 30_000,
  })

  const setTab = (tab: FilterTab) => {
    if (tab === 'all') setSearchParams({})
    else setSearchParams({ filter: tab })
  }

  const openCount     = tickets?.filter((t) => normalizeStatus(t.status) !== 'resolved').length ?? 0
  const resolvedCount = tickets?.filter((t) => normalizeStatus(t.status) === 'resolved').length ?? 0

  const visible = (tickets ?? [])
    .filter((t) => {
      if (activeTab === 'open') return normalizeStatus(t.status) !== 'resolved'
      if (activeTab === 'resolved') return normalizeStatus(t.status) === 'resolved'
      return true
    })
    .filter((t) => !search.trim() || t.ticket_id.toLowerCase().includes(search.trim().toLowerCase()))

  return (
    <div className="space-y-5">
      <PageHeader
        title="My Tickets"
        description="Every ticket you've submitted, and where it stands"
        actions={
          <button onClick={() => navigate('/enduser/submit')} className="btn-primary">
            <PlusCircle className="h-4 w-4" />
            Submit a Ticket
          </button>
        }
      />

      {isError && <ErrorBanner message="Failed to load your tickets." onRetry={() => refetch()} />}

      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex gap-1 p-1 bg-sunken rounded-lg w-fit">
          {(['all', 'open', 'resolved'] as FilterTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setTab(tab)}
              className={cn(
                'px-3 py-1.5 rounded-md text-xs font-medium transition-colors capitalize',
                activeTab === tab ? 'bg-surface text-ink shadow-sm' : 'text-faint hover:text-body',
              )}
            >
              {tab === 'all' ? `All (${tickets?.length ?? 0})`
                : tab === 'open' ? `Open (${openCount})`
                : `Resolved (${resolvedCount})`}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search ticket ID…"
            className="input-base pl-8 w-48 text-sm"
          />
        </div>
      </div>

      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="flex justify-center py-16"><LoadingSpinner size="lg" /></div>
        ) : visible.length === 0 ? (
          <div className="text-center py-16">
            <Inbox className="h-10 w-10 text-line mx-auto mb-3" />
            <p className="text-sm text-faint">
              {tickets?.length ? 'No tickets match the current filter' : "You haven't submitted any tickets yet"}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-line">
            {visible.map((t) => {
              const bucket = normalizeStatus(t.status)
              return (
                <div key={t.ticket_id} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-sunken transition-colors">
                  <div className="min-w-0">
                    <p className="text-sm font-mono text-ink">{t.ticket_id}</p>
                    <p className="text-xs text-faint mt-0.5">
                      Submitted <span title={formatDateTime(t.submitted_at)}>{formatRelativeTime(t.submitted_at)}</span>
                      {t.processed_at && (
                        <> · AURA responded <span title={formatDateTime(t.processed_at)}>{formatRelativeTime(t.processed_at)}</span></>
                      )}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {t.abstained && <Badge tone="critical" dot>No KB match</Badge>}
                    {t.confidence_score != null && <ConfidenceScoreBadge score={t.confidence_score} />}
                    <Badge tone={STATUS_TONES[bucket]} dot>{t.status}</Badge>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
