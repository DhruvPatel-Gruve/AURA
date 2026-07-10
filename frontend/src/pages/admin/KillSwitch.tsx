import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Power, AlertTriangle } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { useKillSwitchStatus } from '@/hooks/useKillSwitchStatus'
import { useConfigStore } from '@/store/configStore'
import { Modal } from '@/components/ui/Modal'
import { Badge } from '@/components/ui/Badge'
import { PageHeader } from '@/components/ui/PageHeader'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatDateTime, formatRelativeTime } from '@/utils/formatters'
import { cn } from '@/utils/cn'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'

export default function KillSwitch() {
  const qc = useQueryClient()
  const killSwitchActive = useConfigStore((s) => s.killSwitchActive)
  const providerLabel    = ITSM_PROVIDER_SHORT_LABELS[useConfigStore((s) => s.itsmProvider)]
  const { data: ksStatus, isLoading } = useKillSwitchStatus()
  const [confirmOpen, setConfirmOpen] = useState(false)

  const enableMutation = useMutation({
    mutationFn: adminApi.enableKillSwitch,
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'kill-switch'] }); setConfirmOpen(false) },
  })

  const disableMutation = useMutation({
    mutationFn: adminApi.disableKillSwitch,
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'kill-switch'] }); setConfirmOpen(false) },
  })

  const isPending = enableMutation.isPending || disableMutation.isPending

  const handleToggle = () => {
    if (killSwitchActive) {
      enableMutation.mutate()   // resume: enable AURA (aura_enabled → true)
    } else {
      setConfirmOpen(true)      // suspend: show confirm first
    }
  }

  const confirmActivate = () => disableMutation.mutate()  // suspend: disable AURA (aura_enabled → false)

  return (
    <div className="space-y-5">
      <PageHeader
        title="Kill Switch"
        description="Instantly halt all AURA autonomous processing"
      />

      {/* Main status panel */}
      <div className={cn(
        'card p-6',
        killSwitchActive ? 'spine-critical' : 'spine-agent',
      )}>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p className="overline-label mb-2">Pipeline State</p>
            <p className={cn(
              'font-mono text-2xl font-semibold tracking-tight',
              killSwitchActive
                ? 'text-red-600 dark:text-red-400'
                : 'text-emerald-700 dark:text-emerald-400',
            )}>
              {killSwitchActive ? 'SUSPENDED' : 'ACTIVE'}
            </p>
            <p className="text-sm text-body mt-1">
              {killSwitchActive
                ? 'AURA is not processing any tickets'
                : 'AURA is running and processing tickets'}
            </p>
            {!isLoading && ksStatus?.changed_at && (
              <p className="mt-3 font-mono text-xs text-faint">
                Last changed {formatRelativeTime(ksStatus.changed_at)}
                {ksStatus.changed_by && ` by ${ksStatus.changed_by}`}
              </p>
            )}
          </div>

          <button
            onClick={handleToggle}
            disabled={isPending || isLoading}
            className={killSwitchActive ? 'btn-primary' : 'btn-danger'}
          >
            {isPending ? (
              <LoadingSpinner size="sm" className="text-white" />
            ) : (
              <Power className="h-4 w-4" />
            )}
            {killSwitchActive ? 'Resume AURA' : 'Suspend AURA'}
          </button>
        </div>
      </div>

      {/* Info cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <h2 className="overline-label mb-3">When Suspended</h2>
          <ul className="space-y-1.5 text-sm text-body">
            <li>• All new {providerLabel} tickets skip the agent pipeline</li>
            <li>• No new comments are posted to {providerLabel}</li>
            <li>• Existing tickets already in the low-confidence queue remain accessible</li>
            <li>• Knowledge ingestion continues on its schedule</li>
          </ul>
        </div>
        <div className="card p-5">
          <h2 className="overline-label mb-3">Status Details</h2>
          {isLoading ? (
            <div className="space-y-2">
              {[1,2,3].map((i) => (
                <div key={i} className="skeleton h-4" />
              ))}
            </div>
          ) : (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between items-center">
                <span className="text-body">Current state</span>
                <Badge tone={killSwitchActive ? 'critical' : 'success'} dot mono>
                  {killSwitchActive ? 'KILL SWITCH ON' : 'KILL SWITCH OFF'}
                </Badge>
              </div>
              {ksStatus?.changed_at && (
                <div className="flex justify-between">
                  <span className="text-body">Last changed</span>
                  <span className="font-mono text-ink">{formatDateTime(ksStatus.changed_at)}</span>
                </div>
              )}
              {ksStatus?.changed_by && (
                <div className="flex justify-between">
                  <span className="text-body">Changed by</span>
                  <span className="font-mono text-ink">{ksStatus.changed_by}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Confirmation modal — activate */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Suspend AURA?"
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-3 rounded-lg spine-critical bg-red-50 dark:bg-red-900/20">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <p className="text-sm text-red-700 dark:text-red-300">
              This will immediately halt all autonomous ticket processing. No new AI responses
              will be posted to {providerLabel} until AURA is resumed. This action is reversible.
            </p>
          </div>
          <p className="text-sm text-body">
            Are you sure you want to suspend AURA?
          </p>
          <div className="flex justify-end gap-2">
            <button onClick={() => setConfirmOpen(false)} className="btn-ghost">
              Cancel
            </button>
            <button
              onClick={confirmActivate}
              disabled={disableMutation.isPending}
              className="btn-danger"
            >
              {disableMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : null}
              Yes, Suspend AURA
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
