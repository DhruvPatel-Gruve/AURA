import { useQuery } from '@tanstack/react-query'
import { dashboardApi } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatDateTime, formatRelativeTime } from '@/utils/formatters'
import { useConfigStore } from '@/store/configStore'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'

interface HealthCardProps {
  label:  string
  value:  string
  status: 'good' | 'warn' | 'bad' | 'neutral'
  sub?:   string
}

const STATUS_TONE: Record<HealthCardProps['status'], BadgeTone> = {
  good:    'success',
  warn:    'warn',
  bad:     'critical',
  neutral: 'neutral',
}

const STATUS_LABELS: Record<HealthCardProps['status'], string> = {
  good:    'Up',
  warn:    'Degraded',
  bad:     'Down',
  neutral: 'Neutral',
}

function HealthCard({ label, value, status, sub }: HealthCardProps) {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="overline-label">{label}</p>
          <p className="mt-1 text-xl font-mono font-semibold text-ink tabular-nums">
            {value}
          </p>
          {sub && (
            <p className="mt-0.5 text-xs text-faint">{sub}</p>
          )}
        </div>
        <Badge tone={STATUS_TONE[status]} dot>
          {STATUS_LABELS[status]}
        </Badge>
      </div>
    </div>
  )
}

function uptimeLabel(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export default function SystemHealth() {
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[useConfigStore((s) => s.itsmProvider)]
  const { data: health, isLoading, dataUpdatedAt } = useQuery({
    queryKey:        ['dashboard', 'admin', 'health'],
    queryFn:         dashboardApi.getAdminHealth,
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="System Health"
        description="Live system metrics — refreshes every 30 seconds"
        actions={dataUpdatedAt > 0 ? (
          <p className="text-xs font-mono text-faint">
            Updated {formatRelativeTime(new Date(dataUpdatedAt).toISOString())}
          </p>
        ) : undefined}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <HealthCard
          label="API Uptime"
          value={health ? uptimeLabel(health.api_uptime_seconds) : '—'}
          status="good"
          sub="FastAPI server"
        />
        <HealthCard
          label="WebSocket Connections"
          value={health ? String(health.ws_connections) : '—'}
          status="neutral"
          sub="Active users"
        />
        <HealthCard
          label="Gemini API Latency"
          value={health ? `${Math.round(health.gemini_latency_ms)}ms` : '—'}
          status={health
            ? health.gemini_latency_ms < 300 ? 'good'
            : health.gemini_latency_ms < 800 ? 'warn'
            : 'bad'
            : 'neutral'}
          sub="text-embedding-004"
        />
        <HealthCard
          label="Qdrant Query Speed"
          value={health ? `${Math.round(health.qdrant_query_ms)}ms` : '—'}
          status={health
            ? health.qdrant_query_ms < 50 ? 'good'
            : health.qdrant_query_ms < 200 ? 'warn'
            : 'bad'
            : 'neutral'}
          sub="Vector search P50"
        />
        <HealthCard
          label="Scheduler"
          value={health ? (health.scheduler_running ? 'Running' : 'Stopped') : '—'}
          status={health ? (health.scheduler_running ? 'good' : 'bad') : 'neutral'}
          sub="APScheduler"
        />
        <HealthCard
          label={`${providerLabel} Poll`}
          value={health?.jsm_poll_last_run ? formatRelativeTime(health.jsm_poll_last_run) : 'Never'}
          status={health?.jsm_poll_last_run ? 'good' : 'neutral'}
          sub={health?.jsm_poll_next_run ? `Next: ${formatRelativeTime(health.jsm_poll_next_run)}` : undefined}
        />
      </div>

      {/* Detail table */}
      {health && (
        <div className="card p-5">
          <h2 className="overline-label mb-3">
            Raw Metrics
          </h2>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-faint">Uptime (seconds)</span>
              <span className="font-mono tabular-nums font-medium">{health.api_uptime_seconds.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">WS connections</span>
              <span className="font-mono tabular-nums font-medium">{health.ws_connections}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Gemini latency</span>
              <span className="font-mono tabular-nums font-medium">{health.gemini_latency_ms.toFixed(1)}ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">Qdrant latency</span>
              <span className="font-mono tabular-nums font-medium">{health.qdrant_query_ms.toFixed(1)}ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">{providerLabel} last poll</span>
              <span className="font-mono font-medium">
                {health.jsm_poll_last_run ? formatDateTime(health.jsm_poll_last_run) : 'Never'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-faint">{providerLabel} next poll</span>
              <span className="font-mono font-medium">
                {health.jsm_poll_next_run ? formatDateTime(health.jsm_poll_next_run) : '—'}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
