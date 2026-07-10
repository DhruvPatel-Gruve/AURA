import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatDateTime, formatRelativeTime, humanize } from '@/utils/formatters'
import { useConfigStore } from '@/store/configStore'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'
import type { RollbackRecord } from '@/api/types'

export default function RollbackHistory() {
  const qc = useQueryClient()
  const provider      = useConfigStore((s) => s.itsmProvider)
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[provider]
  const [confirmRecord, setConfirmRecord] = useState<RollbackRecord | null>(null)
  const [ticketId, setTicketId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [page, setPage]         = useState(1)

  const filters = {
    ...(ticketId ? { ticket_id: ticketId } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    page,
  }

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'rollback', filters],
    queryFn:  () => adminApi.getRollbackHistory(filters),
  })
  const records = data?.items ?? []

  const rollbackMutation = useMutation({
    mutationFn: (id: string) => adminApi.triggerRollback(id),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'rollback'] }); setConfirmRecord(null) },
  })

  const ACTION_LABELS: Record<string, string> = {
    comment_posted:     'Comment Posted',
    ticket_transitioned:'Ticket Transitioned',
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Rollback History" description={`Undo AURA-generated actions posted to ${providerLabel}`} />

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
          <input
            type="text"
            value={ticketId}
            onChange={(e) => { setPage(1); setTicketId(e.target.value) }}
            placeholder="Search ticket ID…"
            className="input-base pl-8 w-48 text-sm"
          />
        </div>
        <input type="date" value={dateFrom} onChange={(e) => { setPage(1); setDateFrom(e.target.value) }} className="input-base text-sm" />
        <span className="text-xs text-faint">to</span>
        <input type="date" value={dateTo} onChange={(e) => { setPage(1); setDateTo(e.target.value) }} className="input-base text-sm" />
      </div>

      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <LoadingSpinner />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10">
                <tr>
                  {['Ticket', 'Action', 'Actor', 'Created', 'Rolled Back', ''].map((h) => (
                    <th key={h} className="table-head">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr
                    key={r.action_id}
                    className={`hover:bg-sunken transition-colors ${r.rolled_back_at ? 'spine-neutral' : 'spine-warn'}`}
                  >
                    <td className="table-cell font-mono text-xs text-ink font-medium">
                      {r.ticket_id}
                    </td>
                    <td className="table-cell text-body">
                      {ACTION_LABELS[r.action_type] ?? humanize(r.action_type)}
                    </td>
                    <td className="table-cell text-body">{r.actor}</td>
                    <td className="table-cell font-mono text-faint">
                      <span title={formatDateTime(r.created_at)}>
                        {formatRelativeTime(r.created_at)}
                      </span>
                    </td>
                    <td className="table-cell">
                      {r.rolled_back_at ? (
                        <Badge tone="neutral" mono>
                          {formatRelativeTime(r.rolled_back_at)}
                        </Badge>
                      ) : (
                        <span className="text-faint text-xs">—</span>
                      )}
                    </td>
                    <td className="table-cell">
                      {!r.rolled_back_at && (
                        <button
                          onClick={() => setConfirmRecord(r)}
                          className="btn-danger !px-2 !py-1 text-xs"
                        >
                          <RotateCcw className="h-3.5 w-3.5 mr-1" />
                          Undo
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {records?.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-faint">
                      No rollback records found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-faint font-mono tabular-nums">
            Page {data.page} of {data.pages} · {data.total} total
          </p>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="btn-ghost !p-1.5 disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
              disabled={page === data.pages}
              className="btn-ghost !p-1.5 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Confirm rollback modal */}
      <Modal
        open={!!confirmRecord}
        onClose={() => setConfirmRecord(null)}
        title="Confirm Rollback"
      >
        {confirmRecord && (
          <div className="space-y-4">
            <p className="text-sm text-body">
              This will delete the AURA-generated comment from ticket{' '}
              <span className="font-mono font-semibold">{confirmRecord.ticket_id}</span>{' '}
              in {providerLabel}. This action cannot be undone.
            </p>
            {confirmRecord.action_type === 'comment_posted' && provider === 'zendesk' && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Note: Zendesk's API doesn't support deleting individual comments — this
                rollback will be recorded, but the original comment will remain on the ticket.
              </p>
            )}
            <div className="p-3 rounded-lg bg-sunken text-sm space-y-1">
              <div className="flex justify-between">
                <span className="text-faint">Action</span>
                <span>{ACTION_LABELS[confirmRecord.action_type] ?? humanize(confirmRecord.action_type)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-faint">Created by</span>
                <span>{confirmRecord.actor}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-faint">Created at</span>
                <span className="font-mono">{formatDateTime(confirmRecord.created_at)}</span>
              </div>
            </div>
            {rollbackMutation.isError && (
              <p className="text-xs text-red-500">Rollback failed. Please try again.</p>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmRecord(null)} className="btn-ghost">Cancel</button>
              <button
                onClick={() => rollbackMutation.mutate(confirmRecord.action_id)}
                disabled={rollbackMutation.isPending}
                className="btn-danger"
              >
                {rollbackMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : <RotateCcw className="h-4 w-4" />}
                Confirm Rollback
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
