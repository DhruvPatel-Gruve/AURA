import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckSquare, Clock, AlertCircle, ChevronLeft, ChevronRight, ArrowUp, ArrowDown } from 'lucide-react'
import { dashboardApi } from '@/api/dashboard.api'
import type { ManagerApprovalsParams } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { ConfidenceScoreBadge } from '@/components/ui/ConfidenceScoreBadge'
import { Badge } from '@/components/ui/Badge'
import { formatRelativeTime } from '@/utils/formatters'
import { cn } from '@/utils/cn'

type SortBy = ManagerApprovalsParams['sort_by']
const PAGE_SIZE = 20

function SortableHeader({
  label, column, sortBy, sortDir, onSort,
}: {
  label:   string
  column:  SortBy
  sortBy:  SortBy
  sortDir: 'asc' | 'desc'
  onSort:  (column: SortBy) => void
}) {
  const active = sortBy === column
  return (
    <th className="text-left pb-2 text-overline font-medium uppercase text-body">
      <button
        onClick={() => onSort(column)}
        className={cn('flex items-center gap-1 hover:text-ink', active && 'text-ink')}
      >
        {label}
        {active && (sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}

export default function ApprovalQueue() {
  const [teamId, setTeamId]     = useState('')
  const [status, setStatus]     = useState<'' | 'abstained' | 'low_confidence'>('')
  const [minConf, setMinConf]   = useState('')
  const [sortBy, setSortBy]     = useState<SortBy>('queued_at')
  const [sortDir, setSortDir]   = useState<'asc' | 'desc'>('asc')
  const [page, setPage]         = useState(1)

  const params: ManagerApprovalsParams = {
    team_id: teamId || undefined,
    status: status || undefined,
    min_confidence: minConf ? Number(minConf) : undefined,
    sort_by: sortBy,
    sort_dir: sortDir,
    page,
    page_size: PAGE_SIZE,
  }

  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'approvals', params],
    queryFn:  () => dashboardApi.getManagerApprovals(params),
    refetchInterval: 30_000,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const pages = Math.ceil(total / PAGE_SIZE)

  const abstainedCount = items.filter((i) => i.abstained).length
  const lowConfCount   = items.filter((i) => !i.abstained && (i.confidence_score ?? 1) < 0.8).length

  const handleSort = (column: SortBy) => {
    setPage(1)
    if (sortBy === column) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortBy(column); setSortDir('asc') }
  }

  const resetToPage1 = <T,>(setter: (v: T) => void) => (v: T) => { setPage(1); setter(v) }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Approval Queue"
        description="Unresolved items that need technician or manager attention"
      />

      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="Pending Items"
          value={total}
          icon={CheckSquare}
          delta={{ label: 'awaiting action', positive: total === 0 }}
        />
        <StatCard
          label="Abstentions (this page)"
          value={abstainedCount}
          icon={AlertCircle}
          delta={{ label: 'AURA declined', positive: abstainedCount === 0 }}
        />
        <StatCard
          label="Low Confidence (this page)"
          value={lowConfCount}
          icon={Clock}
          delta={{ label: 'below 80% confidence', positive: lowConfCount === 0 }}
        />
      </div>

      <div className="card p-4 spine-active">
        <p className="text-sm text-body">
          <strong className="text-ink">Manager view:</strong> These items are visible to technicians for action.
          As manager, use this to monitor backlog and identify categories needing more knowledge base coverage.
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <input
          type="text"
          value={teamId}
          onChange={(e) => resetToPage1(setTeamId)(e.target.value)}
          placeholder="Filter by team ID…"
          className="input-base w-48 text-sm"
        />
        <select
          value={status}
          onChange={(e) => resetToPage1(setStatus)(e.target.value as typeof status)}
          className="input-base w-44 text-sm"
        >
          <option value="">All statuses</option>
          <option value="abstained">Abstained</option>
          <option value="low_confidence">Low Confidence</option>
        </select>
        <input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={minConf}
          onChange={(e) => resetToPage1(setMinConf)(e.target.value)}
          placeholder="Min confidence…"
          className="input-base w-36 text-sm"
        />
      </div>

      <div className="card p-5">
        <h2 className="overline-label mb-3">Pending Queue Items</h2>
        {isLoading ? (
          <div className="flex justify-center py-12"><LoadingSpinner size="lg" /></div>
        ) : items.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line">
                    <th className="text-left pb-2 pl-3 text-overline font-medium uppercase text-body">Ticket ID</th>
                    <SortableHeader label="Team" column="team_id" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                    <th className="text-left pb-2 text-overline font-medium uppercase text-body">Status</th>
                    <SortableHeader label="Confidence" column="confidence_score" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                    <SortableHeader label="Queued" column="queued_at" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {items.map((item) => (
                    <tr
                      key={item.queue_id}
                      className={`hover:bg-sunken ${item.abstained ? 'spine-critical' : 'spine-warn'}`}
                    >
                      <td className="py-2.5 pl-3 font-mono text-xs text-body">
                        {item.ticket_id}
                      </td>
                      <td className="py-2.5 text-body text-xs">
                        {item.team_id || '—'}
                      </td>
                      <td className="py-2.5">
                        {item.abstained ? (
                          <Badge tone="critical" dot>Abstained</Badge>
                        ) : (
                          <Badge tone="warn" dot>Low Confidence</Badge>
                        )}
                      </td>
                      <td className="py-2.5">
                        <ConfidenceScoreBadge score={item.confidence_score} />
                      </td>
                      <td className="py-2.5 font-mono text-xs text-faint whitespace-nowrap">
                        {formatRelativeTime(item.queued_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pages > 1 && (
              <div className="flex items-center justify-between mt-4">
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
                  <span className="text-xs text-body px-2 font-mono tabular-nums">{page} / {pages}</span>
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
        ) : (
          <div className="text-center py-12">
            <CheckSquare className="h-12 w-12 text-faint mx-auto mb-3" />
            <p className="text-sm font-medium text-body">Queue is clear</p>
            <p className="text-xs text-faint mt-1">
              All items have been reviewed
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
