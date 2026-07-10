import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { X, User, Clock, MessageSquare, GitBranch } from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { cn } from '@/utils/cn'
import { formatDateTime, humanize } from '@/utils/formatters'

const ACTION_TONE: Record<string, BadgeTone> = {
  comment_posted:           'success',
  held_low_confidence:      'warn',
  abstained_no_kb_coverage: 'warn',
  rejected_by_technician:   'critical',
  rolled_back_by_technician:'critical',
  halted_kill_switch:       'neutral',
  pipeline_error:           'critical',
}

interface Props {
  ticketId: string | null
  onClose: () => void
}

/** Slide-in inspector for a tree leaf — the manager's x-ray of one ticket:
 * what AURA decided at every pipeline node, who owns it, and where it stands. */
export function TicketDetailDrawer({ ticketId, onClose }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['tickets', ticketId ?? ''],
    queryFn:  () => ticketsApi.getTicket(ticketId!),
    enabled:  !!ticketId,
  })

  return (
    <AnimatePresence>
      {ticketId && (
        <>
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[70] bg-black/30"
            onClick={onClose}
          />
          <motion.aside
            key="drawer"
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.22, ease: 'easeOut' }}
            className="fixed inset-y-0 right-0 z-[80] w-[440px] max-w-[92vw] bg-surface border-l border-line shadow-card-md flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-5 h-14 border-b border-line shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-sm font-semibold text-ink">{ticketId}</span>
                {data && (
                  <Badge tone={ACTION_TONE[data.action_taken] ?? 'neutral'}>
                    {humanize(data.action_taken)}
                  </Badge>
                )}
              </div>
              <button onClick={onClose} className="btn-ghost !px-2" aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {isLoading && (
                <div className="space-y-3">
                  <div className="skeleton h-5 w-3/4" />
                  <div className="skeleton h-4 w-full" />
                  <div className="skeleton h-4 w-5/6" />
                  <div className="skeleton h-24 w-full" />
                </div>
              )}

              {data && (
                <>
                  {/* What was asked */}
                  <section>
                    <h3 className="overline-label mb-1.5">Request</h3>
                    <p className="text-sm font-medium text-ink">{data.summary ?? 'Unavailable (live fetch failed)'}</p>
                    {data.description && (
                      <p className="mt-1 text-xs text-body whitespace-pre-wrap line-clamp-6">{data.description}</p>
                    )}
                  </section>

                  {/* Facts grid */}
                  <section className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
                    <Fact label="Status"     value={data.status ?? '—'} />
                    <Fact label="Priority"   value={data.priority ?? '—'} />
                    <Fact label="Category"   value={data.category ?? '—'} />
                    <Fact
                      label="Confidence"
                      value={data.confidence_score != null ? `${(data.confidence_score * 100).toFixed(0)}%` : '—'}
                      mono
                    />
                    <Fact label="Auto-comment" value={data.auto_comment_enabled == null ? '—' : data.auto_comment_enabled ? 'Enabled' : 'Off (queue-only)'} />
                    <Fact label="Processed"  value={formatDateTime(data.created_at)} mono />
                  </section>

                  {/* Assignment */}
                  <section className="card !shadow-none p-3 flex items-center gap-2.5">
                    <User className="h-4 w-4 text-faint shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-ink truncate">
                        {data.assigned_to ?? 'Unassigned'}
                      </p>
                      <p className="text-[11px] text-faint">
                        {data.assigned_to
                          ? data.acknowledged_at
                            ? `Acknowledged ${formatDateTime(data.acknowledged_at)}`
                            : 'Not yet acknowledged'
                          : 'No current assignment'}
                      </p>
                    </div>
                    {data.assigned_to && (
                      <Badge tone={data.acknowledged_at ? 'success' : 'warn'} dot>
                        {data.acknowledged_at ? 'Acked' : 'Pending'}
                      </Badge>
                    )}
                  </section>

                  {/* Pipeline timeline */}
                  <section>
                    <h3 className="overline-label mb-2 flex items-center gap-1.5">
                      <GitBranch className="h-3.5 w-3.5" /> Pipeline decisions
                    </h3>
                    {data.audit_steps.length ? (
                      <ol className="relative border-l border-line ml-1.5 space-y-3">
                        {data.audit_steps.map((s, i) => (
                          <li key={i} className="ml-4">
                            <span className={cn(
                              'absolute -left-[5px] mt-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface',
                              i === data.audit_steps.length - 1 ? 'bg-accent' : 'bg-line',
                            )} />
                            <p className="text-xs font-medium text-ink font-mono">
                              {humanize(s.node_name.replace(/_node$/, ''))}
                            </p>
                            <p className="text-[11px] text-body">{s.decision}</p>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="text-xs text-faint">No pipeline steps recorded</p>
                    )}
                  </section>

                  {/* Conversation */}
                  <section>
                    <h3 className="overline-label mb-2 flex items-center gap-1.5">
                      <MessageSquare className="h-3.5 w-3.5" /> Comments ({data.comments.length})
                    </h3>
                    {data.comments.length ? (
                      <div className="space-y-2">
                        {data.comments.slice(-4).map((c, i) => (
                          <div key={i} className="rounded-md bg-sunken p-2.5">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <span className="text-[11px] font-medium text-ink truncate">{c.author}</span>
                              <span className="text-[10px] font-mono text-faint whitespace-nowrap flex items-center gap-1">
                                <Clock className="h-3 w-3" />{formatDateTime(c.created)}
                              </span>
                            </div>
                            <p className="text-xs text-body whitespace-pre-wrap line-clamp-4">{c.body}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-faint">No comments on the live ticket</p>
                    )}
                  </section>
                </>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-faint">{label}</p>
      <p className={cn('text-xs text-ink mt-0.5', mono && 'font-mono')}>{value}</p>
    </div>
  )
}
