import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X, Edit2, ExternalLink, ChevronUp } from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import type { LowConfQueueEntry } from '@/api/types'
import { ConfidenceMeter } from '@/components/ui/ConfidenceMeter'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { Badge } from '@/components/ui/Badge'
import { MarkdownLite } from '@/components/ui/MarkdownLite'
import { cn } from '@/utils/cn'
import { useConfigStore } from '@/store/configStore'
import { useAuthStore } from '@/store/authStore'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'

export function AURASuggestionPanel({
  item,
  onClose,
  acknowledgedAt,
}: {
  item: LowConfQueueEntry
  onClose: () => void
  acknowledgedAt?: string | null
}) {
  const qc = useQueryClient()
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[useConfigStore((s) => s.itsmProvider)]
  const { role, teamId } = useAuthStore((s) => ({ role: s.role, teamId: s.teamId }))
  // Technicians can only act on their own team's tickets — everything else
  // is visible (GET /queue has no team filter) but read-only. Admins bypass
  // this entirely; the backend enforces the same rule on approve/reject/edit.
  const canAct = role === 'admin' || item.team_id === teamId
  // Posting a comment (Approve/Edit&Post) requires acknowledging the ticket
  // first — the backend enforces this too; this just avoids a round-trip.
  const canPost = role === 'admin' || !!acknowledgedAt
  const [editText, setEditText]         = useState(item.formatted_comment)
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject]     = useState(false)
  const [showEdit, setShowEdit]         = useState(false)
  const [actionMsg, setActionMsg]       = useState<string | null>(null)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['technician', 'queue-lcq'] })
    qc.invalidateQueries({ queryKey: ['technician', 'stats'] })
    qc.invalidateQueries({ queryKey: ['technician', 'ticket-list'] })
    qc.invalidateQueries({ queryKey: ['ticket', item.ticket_id] })
    onClose()
  }

  const approveMutation = useMutation({
    mutationFn: () => ticketsApi.approveQueueItem(item.queue_id),
    onSuccess:  () => { setActionMsg(`Approved — comment posted to ${providerLabel}`); setTimeout(invalidate, 1000) },
    onError:    () => setActionMsg('Failed to approve. Please try again.'),
  })
  const rejectMutation = useMutation({
    mutationFn: () => ticketsApi.rejectQueueItem(item.queue_id, rejectReason),
    onSuccess:  () => { setActionMsg('Rejected'); setTimeout(invalidate, 800) },
    onError:    () => setActionMsg('Failed to reject. Please try again.'),
  })
  const editMutation = useMutation({
    mutationFn: () => ticketsApi.editQueueItem(item.queue_id, editText),
    onSuccess:  () => { setActionMsg(`Edited and posted to ${providerLabel}`); setTimeout(invalidate, 1000) },
    onError:    () => setActionMsg('Failed to post. Please try again.'),
  })

  const busy = approveMutation.isPending || rejectMutation.isPending || editMutation.isPending

  return (
    <div className="border-t border-line bg-sunken p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="overline-label">AURA Suggestion</h3>
          <ConfidenceMeter score={item.confidence_score} />
          {item.abstained && (
            <Badge tone="critical" dot>Abstained</Badge>
          )}
        </div>
        <button onClick={onClose} className="text-faint hover:text-body">
          <ChevronUp className="h-4 w-4" />
        </button>
      </div>

      {!showEdit ? (
        <div className="rounded-lg border border-line bg-surface p-4">
          <p className="text-xs font-medium text-faint mb-2">Draft reply for {providerLabel}:</p>
          <div className="text-sm text-ink leading-relaxed">
            {item.formatted_comment
              ? <MarkdownLite text={item.formatted_comment} />
              : '(No draft generated — AURA abstained)'}
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs font-medium text-faint">Edit before posting:</p>
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={6}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink resize-y focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      )}

      {item.citations.length > 0 && (
        <div>
          <p className="text-xs font-medium text-faint mb-1.5">Sources used:</p>
          <div className="space-y-1">
            {item.citations.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-body">
                <ExternalLink className="h-3 w-3 shrink-0" />
                <span className="truncate font-mono">{c}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {actionMsg && (
        <p className={cn(
          'text-xs font-medium',
          actionMsg.startsWith('Failed') ? 'text-red-500' : 'text-emerald-600 dark:text-emerald-400',
        )}>
          {actionMsg}
        </p>
      )}

      {showReject && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-body">Reason for rejection:</p>
          <input
            type="text"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="e.g. Incorrect resolution, needs escalation…"
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      )}

      {/* Human controls */}
      <div className="border-t border-line pt-3 space-y-2">
        <p className="overline-label">Human Review</p>
        {!canAct ? (
          <p className="text-xs text-faint">
            Read-only — this ticket belongs to another team. Only that team's technicians can approve, edit, or reject it.
          </p>
        ) : (
        <div className="flex items-center gap-2 flex-wrap">
          {!canPost && !showReject && (
            <p className="text-xs text-amber-600 dark:text-amber-400 basis-full">
              Acknowledge this ticket above before you can approve or edit &amp; post a reply.
            </p>
          )}
          {!showEdit && !showReject && (
            <>
              <button
                onClick={() => approveMutation.mutate()}
                disabled={busy || !!item.abstained || !canPost}
                title={
                  !canPost
                    ? 'Acknowledge the ticket first'
                    : item.abstained ? 'Cannot approve abstention — edit the comment first' : undefined
                }
                className="btn-primary inline-flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {approveMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : <Check className="h-3.5 w-3.5" />}
                Approve & Post
              </button>
              <button
                onClick={() => setShowEdit(true)}
                disabled={busy || !canPost}
                title={!canPost ? 'Acknowledge the ticket first' : undefined}
                className="btn-secondary inline-flex items-center gap-1.5 disabled:opacity-40"
              >
                <Edit2 className="h-3.5 w-3.5" /> Edit & Post
              </button>
              <button
                onClick={() => setShowReject(true)}
                disabled={busy}
                className="btn-danger inline-flex items-center gap-1.5 disabled:opacity-40"
              >
                <X className="h-3.5 w-3.5" /> Reject
              </button>
            </>
          )}
          {showEdit && (
            <>
              <button
                onClick={() => editMutation.mutate()}
                disabled={busy || !editText.trim() || !canPost}
                className="btn-primary inline-flex items-center gap-1.5 disabled:opacity-40"
              >
                {editMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : <Check className="h-3.5 w-3.5" />}
                Post Edited Reply
              </button>
              <button onClick={() => setShowEdit(false)} className="btn-ghost">Cancel</button>
            </>
          )}
          {showReject && (
            <>
              <button
                onClick={() => rejectMutation.mutate()}
                disabled={busy || !rejectReason.trim()}
                className="btn-danger inline-flex items-center gap-1.5 disabled:opacity-40"
              >
                {rejectMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : <X className="h-3.5 w-3.5" />}
                Confirm Reject
              </button>
              <button onClick={() => setShowReject(false)} className="btn-ghost">Cancel</button>
            </>
          )}
        </div>
        )}
      </div>
    </div>
  )
}
