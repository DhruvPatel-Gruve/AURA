import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Activity, Zap, Database, Wifi, Clock, CheckCircle, AlertTriangle,
  Users, Tag, ListChecks, RotateCcw, FileText, MessageSquare,
} from 'lucide-react'
import { dashboardApi } from '@/api/dashboard.api'
import { ingestionApi } from '@/api/ingestion.api'
import { adminApi } from '@/api/admin.api'
import { useConfigStore } from '@/store/configStore'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { StatCard } from '@/components/ui/StatCard'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { formatRelativeTime, formatDateTime, humanize } from '@/utils/formatters'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'

interface QdrantStatsLite {
  documents_count: number
  tickets_count:   number
}

function uptimeLabel(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

type ActivityItem =
  | { kind: 'audit'; id: string; created_at: string; ticket_id: string; action_taken: string }
  | { kind: 'rollback'; id: string; created_at: string; ticket_id: string; action_type: string; rolled_back_at: string | null }

export default function AdminDashboard() {
  const navigate         = useNavigate()
  const killSwitchActive = useConfigStore((s) => s.killSwitchActive)
  const providerLabel    = ITSM_PROVIDER_SHORT_LABELS[useConfigStore((s) => s.itsmProvider)]

  const { data: health, isLoading, isError: healthError, refetch: refetchHealth } = useQuery({
    queryKey:        ['dashboard', 'admin', 'health'],
    queryFn:         dashboardApi.getAdminHealth,
    refetchInterval: 30_000,
  })

  const { data: runs, isError: runsError, refetch: refetchRuns } = useQuery({
    queryKey: ['ingestion', 'runs'],
    queryFn:  ingestionApi.getRuns,
  })

  const { data: qdrantStats } = useQuery({
    queryKey: ['admin', 'qdrant', 'stats'],
    queryFn:  async () => (await adminApi.getQdrantStats()) as unknown as QdrantStatsLite,
    refetchInterval: 30_000,
  })

  const { data: users } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn:  adminApi.getUsers,
  })

  const { data: categories } = useQuery({
    queryKey: ['admin', 'categories'],
    queryFn:  adminApi.getCategories,
  })

  const { data: auditData } = useQuery({
    queryKey: ['admin', 'audit-log', 'overview'],
    queryFn:  () => adminApi.getAuditLog({ page: 1 }),
  })

  const { data: rollbacks } = useQuery({
    queryKey: ['admin', 'rollback', 'overview'],
    queryFn:  () => adminApi.getRollbackHistory({ page: 1 }),
  })

  const lastRun = runs?.[0]
  const recentRuns = runs?.slice(0, 5) ?? []

  const activeUsers = users?.filter((u) => u.is_active).length ?? 0
  const totalUsers  = users?.length ?? 0

  const recentActivity: ActivityItem[] = [
    ...(auditData?.entries.slice(0, 5).map((e) => ({
      kind: 'audit' as const, id: e.entry_id, created_at: e.created_at,
      ticket_id: e.ticket_id, action_taken: e.action_taken,
    })) ?? []),
    ...(rollbacks?.items.slice(0, 5).map((r) => ({
      kind: 'rollback' as const, id: r.action_id, created_at: r.created_at,
      ticket_id: r.ticket_id, action_type: r.action_type, rolled_back_at: r.rolled_back_at,
    })) ?? []),
  ]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 6)

  return (
    <div className="space-y-5">
      <PageHeader title="Admin Dashboard" description="System overview and health" />

      {healthError && <ErrorBanner message="Failed to load system health." onRetry={() => refetchHealth()} />}
      {runsError && <ErrorBanner message="Failed to load ingestion runs." onRetry={() => refetchRuns()} />}

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <StatCard
          label="API Uptime"
          value={health ? uptimeLabel(health.api_uptime_seconds) : '—'}
          icon={Activity}
          loading={isLoading}
          delta={health ? { label: 'Running', positive: true } : undefined}
        />
        <StatCard
          label="WS Connections"
          value={health?.ws_connections ?? '—'}
          icon={Wifi}
          loading={isLoading}
        />
        <StatCard
          label="Gemini Latency"
          value={health ? `${Math.round(health.gemini_latency_ms)}ms` : '—'}
          icon={Zap}
          loading={isLoading}
          delta={health
            ? { label: health.gemini_latency_ms < 500 ? 'Good' : 'Slow', positive: health.gemini_latency_ms < 500 }
            : undefined}
        />
        <StatCard
          label="Qdrant Speed"
          value={health ? `${Math.round(health.qdrant_query_ms)}ms` : '—'}
          icon={Database}
          loading={isLoading}
          delta={health
            ? { label: health.qdrant_query_ms < 100 ? 'Good' : 'Slow', positive: health.qdrant_query_ms < 100 }
            : undefined}
        />
        <StatCard
          label="Scheduler"
          value={killSwitchActive ? 'Halted' : health ? (health.scheduler_running ? 'Running' : 'Stopped') : '—'}
          icon={CheckCircle}
          loading={isLoading}
          delta={killSwitchActive
            ? { label: 'Suspended', positive: false }
            : health
              ? { label: health.scheduler_running ? 'Active' : 'Inactive', positive: !!health.scheduler_running }
              : undefined}
        />
        <StatCard
          label={`${providerLabel} Last Poll`}
          value={killSwitchActive ? 'Halted' : health?.jsm_poll_last_run ? formatRelativeTime(health.jsm_poll_last_run) : 'Never'}
          icon={Clock}
          loading={isLoading}
          delta={killSwitchActive ? { label: 'Suspended', positive: false } : undefined}
        />
      </div>

      {/* Platform overview — clickable tiles into the relevant admin page */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <button onClick={() => navigate('/admin/qdrant')} className="text-left">
          <StatCard label="KB Documents" value={qdrantStats?.documents_count ?? '—'} icon={FileText} className="hover:border-faint/40 transition-colors" />
        </button>
        <button onClick={() => navigate('/admin/categories')} className="text-left">
          <StatCard label="Categories" value={categories?.length ?? '—'} icon={Tag} className="hover:border-faint/40 transition-colors" />
        </button>
        <button onClick={() => navigate('/admin/users')} className="text-left">
          <StatCard
            label="Active Users"
            value={users ? `${activeUsers} / ${totalUsers}` : '—'}
            icon={Users}
            className="hover:border-faint/40 transition-colors"
          />
        </button>
        <button onClick={() => navigate('/admin/audit-log')} className="text-left">
          <StatCard label="Tickets Processed" value={auditData?.total ?? '—'} icon={ListChecks} className="hover:border-faint/40 transition-colors" />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Ticket poller schedule */}
        {health && (
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-3">
              <h2 className="overline-label">{providerLabel} Poller</h2>
              {killSwitchActive && <Badge tone="critical" dot>Halted</Badge>}
            </div>
            {killSwitchActive ? (
              <p className="text-sm text-red-600 dark:text-red-400">
                Polling is suspended. Re-enable AURA to resume automatic {providerLabel} syncing.
              </p>
            ) : (
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-faint">Interval</span>
                  <span className="text-ink font-mono tabular-nums">
                    {health.polling_interval_minutes > 0 ? `${health.polling_interval_minutes} min` : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-faint">Last run</span>
                  <span className="text-ink font-mono">
                    {health.jsm_poll_last_run ? formatDateTime(health.jsm_poll_last_run) : 'Never'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-faint">Next run</span>
                  <span className="text-ink font-mono">
                    {health.jsm_poll_next_run ? formatRelativeTime(health.jsm_poll_next_run) : '—'}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Last ingestion run */}
        <div className="card p-5">
          <h2 className="overline-label mb-3">
            Last Ingestion Run
          </h2>
          {lastRun ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between items-center">
                <span className="text-faint">Status</span>
                <Badge
                  tone={
                    lastRun.status === 'completed' ? 'success'
                    : lastRun.status === 'running'  ? 'warn'
                    : 'critical'
                  }
                  dot
                >
                  {lastRun.status}
                </Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-faint">Indexed / Skipped</span>
                <span className="font-mono tabular-nums">
                  {lastRun.tickets_indexed} / {lastRun.tickets_skipped}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-faint">Chunks created</span>
                <span className="font-mono tabular-nums">{lastRun.chunks_created}</span>
              </div>
              {lastRun.completed_at && (
                <div className="flex justify-between">
                  <span className="text-faint">Completed</span>
                  <span className="font-mono">{formatDateTime(lastRun.completed_at)}</span>
                </div>
              )}
              {lastRun.error_message && (
                <div className="flex items-start gap-2 mt-2 p-2 rounded-md bg-red-50 dark:bg-red-900/20">
                  <AlertTriangle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                  <p className="text-xs text-red-600 dark:text-red-400">{lastRun.error_message}</p>
                </div>
              )}
              {recentRuns.length > 1 && (
                <div className="pt-2 mt-2 border-t border-line">
                  <p className="text-xs text-faint mb-1.5">Recent runs</p>
                  <div className="flex items-center gap-1">
                    {recentRuns.slice().reverse().map((r) => (
                      <span
                        key={r.run_id}
                        title={`${r.status} — ${r.chunks_created} chunks — ${formatDateTime(r.started_at)}`}
                        className={`h-2 flex-1 rounded-full ${
                          r.status === 'completed' ? 'bg-emerald-400 dark:bg-emerald-500'
                          : r.status === 'running'  ? 'bg-amber-400 dark:bg-amber-500'
                          : 'bg-red-400 dark:bg-red-500'
                        }`}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-faint">No ingestion runs yet</p>
          )}
        </div>
      </div>

      {/* Recent activity — merged audit + rollback feed */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="overline-label">Recent Activity</h2>
          <div className="flex gap-3 text-xs">
            <button onClick={() => navigate('/admin/audit-log')} className="text-accent hover:underline">Audit Log →</button>
            <button onClick={() => navigate('/admin/rollback')} className="text-accent hover:underline">Rollbacks →</button>
          </div>
        </div>
        {recentActivity.length ? (
          <div className="space-y-2">
            {recentActivity.map((item) => (
              <div
                key={`${item.kind}-${item.id}`}
                className="flex items-center justify-between py-2 border-b border-line last:border-0 text-sm"
              >
                <div className="flex items-center gap-3 min-w-0">
                  {item.kind === 'rollback'
                    ? <RotateCcw className="h-4 w-4 text-faint shrink-0" />
                    : <MessageSquare className="h-4 w-4 text-accent shrink-0" />
                  }
                  <div className="min-w-0">
                    <p className="font-mono text-body truncate">{item.ticket_id}</p>
                    <p className="text-xs text-faint">
                      {item.kind === 'audit'
                        ? humanize(item.action_taken)
                        : `${humanize(item.action_type)}${item.rolled_back_at ? ' · Rolled Back' : ''}`}
                    </p>
                  </div>
                </div>
                <span className="text-xs font-mono text-faint shrink-0 ml-3">
                  {formatRelativeTime(item.created_at)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-faint">No activity yet</p>
        )}
      </div>

    </div>
  )
}
