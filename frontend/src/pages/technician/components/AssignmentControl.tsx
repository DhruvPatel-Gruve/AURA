import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, UserCheck } from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { useAuthStore } from '@/store/authStore'

// Tickets are always auto-assigned (assignment_node); this only surfaces who's
// assigned and lets the assignee Acknowledge — which cancels the automatic
// reassignment timer (see assignment_service.check_overdue).

export function AssignmentControl({
  ticketId,
  assignedTo,
  acknowledgedAt,
}: {
  ticketId: string
  assignedTo: string | null
  acknowledgedAt: string | null
}) {
  const qc = useQueryClient()
  const userId = useAuthStore((s) => s.userId)

  const acknowledgeMutation = useMutation({
    mutationFn: () => ticketsApi.acknowledgeTicket(ticketId),
    onSuccess:  () => {
      qc.invalidateQueries({ queryKey: ['ticket', ticketId] })
      qc.invalidateQueries({ queryKey: ['technician', 'ticket-list'] })
    },
  })

  if (!assignedTo) {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-faint border border-line">
        <UserCheck className="h-3.5 w-3.5" /> Not yet assigned
      </span>
    )
  }

  if (assignedTo !== userId) {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-faint border border-line">
        <UserCheck className="h-3.5 w-3.5" /> Assigned to another technician
      </span>
    )
  }

  if (acknowledgedAt) {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900">
        <Check className="h-3.5 w-3.5" /> Acknowledged
      </span>
    )
  }

  return (
    <button
      onClick={() => acknowledgeMutation.mutate()}
      disabled={acknowledgeMutation.isPending}
      className="btn-primary inline-flex items-center gap-1.5 text-sm disabled:opacity-40"
    >
      {acknowledgeMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : <UserCheck className="h-3.5 w-3.5" />}
      Acknowledge
    </button>
  )
}
