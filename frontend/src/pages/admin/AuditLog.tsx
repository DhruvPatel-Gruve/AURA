import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Search } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { ConfidenceScoreBadge } from '@/components/ui/ConfidenceScoreBadge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatDateTime, formatRelativeTime, humanize } from '@/utils/formatters'

const ACTION_TONES: Record<string, BadgeTone> = {
  comment_posted:     'success',
  held_low_confidence:'warn',
  abstained_no_kb_coverage: 'critical',
  halted_kill_switch: 'critical',
}

const ACTION_SPINES: Record<string, string> = {
  comment_posted:     'spine-agent',
  held_low_confidence:'spine-warn',
  abstained_no_kb_coverage: 'spine-critical',
  halted_kill_switch: 'spine-critical',
}

const ACTION_LABELS: Record<string, string> = {
  comment_posted:     'Posted',
  held_low_confidence:'Low Confidence',
  abstained_no_kb_coverage: 'Abstained',
  halted_kill_switch: 'Kill Switch',
}

interface Filters {
  ticket_id:   string
  action_type: string
  date_from:   string
  date_to:     string
  page:        number
}

export default function AuditLog() {
  const [filters, setFilters] = useState<Filters>({
    ticket_id: '', action_type: '', date_from: '', date_to: '', page: 1,
  })

  const queryParams = Object.fromEntries(
    Object.entries(filters).filter(([, v]) => v !== '' && v !== 0),
  ) as Record<string, string | number>

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'audit-log', filters],
    queryFn:  () => adminApi.getAuditLog(queryParams),
  })

  const handleExport = async () => {
    try {
      const blob = await adminApi.exportAuditLogCSV(
        Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== '')) as Record<string, string>,
      )
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `audit-log-${new Date().toISOString().slice(0,10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      /* ignore */
    }
  }

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    setFilters((f) => ({ ...f, [key]: value, page: 1 }))

  const entries = data?.entries ?? []
  const total   = data?.total   ?? 0
  const PAGE_SIZE = 20

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit Log"
        description="Immutable record of every AURA decision"
        actions={
          <button onClick={handleExport} className="btn-secondary">
            <Download className="h-4 w-4" />
            Export CSV
          </button>
        }
      />

      {/* Filter bar */}
      <div className="card p-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
            <input
              type="text"
              placeholder="Ticket ID"
              className="input-base !pl-8"
              value={filters.ticket_id}
              onChange={(e) => set('ticket_id', e.target.value)}
            />
          </div>
          <select
            className="input-base"
            value={filters.action_type}
            onChange={(e) => set('action_type', e.target.value)}
          >
            <option value="">All actions</option>
            {Object.entries(ACTION_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          <input
            type="date"
            className="input-base"
            value={filters.date_from}
            onChange={(e) => set('date_from', e.target.value)}
          />
          <input
            type="date"
            className="input-base"
            value={filters.date_to}
            onChange={(e) => set('date_to', e.target.value)}
          />
        </div>
      </div>

      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <LoadingSpinner />
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10">
                  <tr>
                    {['Ticket', 'Action', 'Category', 'Priority', 'Confidence', 'Created'].map((h) => (
                      <th key={h} className="table-head">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e) => (
                    <tr
                      key={e.entry_id}
                      className={`hover:bg-sunken transition-colors ${ACTION_SPINES[e.action_taken] ?? 'spine-neutral'}`}
                    >
                      <td className="table-cell font-mono text-xs font-medium text-ink">
                        {e.ticket_id}
                      </td>
                      <td className="table-cell">
                        <Badge tone={ACTION_TONES[e.action_taken] ?? 'neutral'}>
                          {ACTION_LABELS[e.action_taken] ?? humanize(e.action_taken)}
                        </Badge>
                      </td>
                      <td className="table-cell text-body">{e.category ?? '—'}</td>
                      <td className="table-cell text-body">{e.priority ?? '—'}</td>
                      <td className="table-cell font-mono tabular-nums">
                        <ConfidenceScoreBadge score={e.confidence_score} />
                      </td>
                      <td className="table-cell font-mono text-faint">
                        <span title={formatDateTime(e.created_at)}>
                          {formatRelativeTime(e.created_at)}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {entries.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-10 text-center text-sm text-faint">
                        No audit entries match the current filters
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-line">
                <p className="text-xs font-mono tabular-nums text-faint">
                  Showing {Math.min((filters.page - 1) * PAGE_SIZE + 1, total)}–
                  {Math.min(filters.page * PAGE_SIZE, total)} of {total}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}
                    disabled={filters.page === 1}
                    className="btn-ghost !px-3 !py-1 text-xs disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}
                    disabled={filters.page * PAGE_SIZE >= total}
                    className="btn-ghost !px-3 !py-1 text-xs disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
