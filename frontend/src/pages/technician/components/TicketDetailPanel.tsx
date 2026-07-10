import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronUp, RotateCcw, Check } from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import type { LowConfQueueEntry } from '@/api/types'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { AutonomyBadge } from '@/components/ui/AutonomyBadge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { MarkdownLite } from '@/components/ui/MarkdownLite'
import { formatRelativeTime, humanize } from '@/utils/formatters'
import { useAuthStore } from '@/store/authStore'
import { AssignmentControl } from './AssignmentControl'
import { AURASuggestionPanel } from './AURASuggestionPanel'

// Expanded row for a ticket in the unified queue — acknowledge (if you're the
// assignee) and act on AURA's suggestion (if one is pending) from one place,
// no navigating between separate sections.

export function TicketDetailPanel({
  ticketId,
  queueEntry,
  onClose,
}: {
  ticketId: string
  queueEntry?: LowConfQueueEntry
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['ticket', ticketId],
    queryFn:  () => ticketsApi.getTicket(ticketId),
  })
  const { role } = useAuthStore((s) => ({ role: s.role }))
  const isAdmin = role === 'admin'
  const canPost = isAdmin || !!data?.acknowledged_at

  const [showCorrection, setShowCorrection] = useState(false)
  const [correctionText, setCorrectionText] = useState('')

  const invalidateTicket = () => {
    qc.invalidateQueries({ queryKey: ['ticket', ticketId] })
    qc.invalidateQueries({ queryKey: ['technician', 'ticket-list'] })
  }

  const rollbackMutation = useMutation({
    mutationFn: () => ticketsApi.rollbackComment(ticketId),
    onSuccess:  () => { setShowCorrection(true); setCorrectionText(''); invalidateTicket() },
  })
  const postMutation = useMutation({
    mutationFn: () => ticketsApi.postComment(ticketId, correctionText),
    onSuccess:  () => { setShowCorrection(false); invalidateTicket() },
  })

  return (
    <div className="border-t border-line bg-sunken p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="overline-label">Ticket Detail</h3>
        <div className="flex items-center gap-2">
          {data && (
            <AssignmentControl
              ticketId={ticketId}
              assignedTo={data.assigned_to}
              acknowledgedAt={data.acknowledged_at}
            />
          )}
          <button onClick={onClose} className="text-faint hover:text-body">
            <ChevronUp className="h-4 w-4" />
          </button>
        </div>
      </div>
      {isLoading ? (
        <LoadingSpinner size="sm" />
      ) : data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-faint">Status</span>
              <StatusBadge status={data.status} />
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Action</span>
              <span className="text-ink text-xs">{humanize(data.action_taken)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Category</span>
              <span className="text-ink">{data.category ?? '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Assigned</span>
              <span className="text-ink font-mono">
                {data.assigned_at ? formatRelativeTime(data.assigned_at) : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Priority</span>
              <span className="text-ink">{data.priority ?? '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Auto Comment</span>
              <AutonomyBadge enabled={data.auto_comment_enabled} />
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Comment ID</span>
              <span className="text-ink font-mono text-xs truncate max-w-[120px]">{data.jsm_comment_id ?? '—'}</span>
            </div>
          </div>

          {(data.summary || data.description) && (
            <div className="rounded-lg border border-line bg-surface p-3.5">
              <p className="text-xs font-medium text-faint mb-1.5">Original question</p>
              {data.summary && (
                <p className="text-sm font-medium text-ink">{data.summary}</p>
              )}
              {data.description && (
                <p className="text-sm text-body mt-1 whitespace-pre-wrap">{data.description}</p>
              )}
            </div>
          )}

          {/* Comment thread — visible no matter the ticket's status (open,
              in progress, or closed), since AURA's posted comments live only
              on the real ticket, never in this DB. */}
          <div className="rounded-lg border border-line bg-surface p-3.5 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-faint">Comments</p>
              {data.rollback_action_id && !showCorrection && (
                <button
                  onClick={() => rollbackMutation.mutate()}
                  disabled={rollbackMutation.isPending || !canPost}
                  title={!canPost ? 'Acknowledge the ticket first' : 'Undo the posted comment and write a corrected reply'}
                  className="btn-secondary !py-1 !px-2 text-xs inline-flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {rollbackMutation.isPending ? <LoadingSpinner size="sm" /> : <RotateCcw className="h-3 w-3" />}
                  Rollback & Correct
                </button>
              )}
            </div>

            {data.comments.length > 0 ? (
              <div className="space-y-3">
                {data.comments.map((c, i) => (
                  <div key={i} className="text-sm">
                    <div className="flex items-baseline justify-between mb-0.5">
                      <span className="text-xs font-medium text-ink">{c.author}</span>
                      <span className="text-xs text-faint font-mono">{formatRelativeTime(c.created)}</span>
                    </div>
                    <div className="text-body leading-relaxed">
                      <MarkdownLite text={c.body} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-faint">No comments on this ticket yet.</p>
            )}

            {data.rollback_action_id && !canPost && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Acknowledge this ticket above before you can roll back and correct this comment.
              </p>
            )}

            {showCorrection && (
              <div className="space-y-2 border-t border-line pt-3">
                <p className="text-xs font-medium text-body">Post the correct answer:</p>
                <textarea
                  value={correctionText}
                  onChange={(e) => setCorrectionText(e.target.value)}
                  rows={5}
                  placeholder="Write the corrected resolution for this ticket…"
                  className="w-full rounded-lg border border-line bg-sunken px-3 py-2 text-sm text-ink resize-y focus:outline-none focus:ring-2 focus:ring-accent/30"
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => postMutation.mutate()}
                    disabled={postMutation.isPending || !correctionText.trim()}
                    className="btn-primary inline-flex items-center gap-1.5 text-xs disabled:opacity-40"
                  >
                    {postMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : <Check className="h-3.5 w-3.5" />}
                    Post Corrected Comment
                  </button>
                  <button onClick={() => setShowCorrection(false)} className="btn-ghost text-xs">Cancel</button>
                </div>
                {postMutation.isError && (
                  <p className="text-xs text-red-500">Failed to post. Please try again.</p>
                )}
              </div>
            )}
          </div>

          {isAdmin && data.audit_steps.length > 0 && (
            <div>
              <p className="text-xs font-medium text-faint mb-2">Agent steps (<span className="font-mono tabular-nums">{data.audit_steps.length}</span>):</p>
              <div className="space-y-1">
                {data.audit_steps.map((step, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="shrink-0 w-4 h-4 rounded-full bg-accent/10 text-accent flex items-center justify-center text-[10px] font-bold font-mono mt-0.5">{i + 1}</span>
                    <div>
                      <span className="font-mono text-body">{step.node_name}</span>
                      <span className="text-faint ml-2">→ {step.decision}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-faint">Could not load ticket detail</p>
      )}

      {queueEntry && (
        <AURASuggestionPanel item={queueEntry} onClose={onClose} acknowledgedAt={data?.acknowledged_at ?? null} />
      )}
    </div>
  )
}
