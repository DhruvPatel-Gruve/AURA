import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Target, TrendingUp, AlertCircle, Zap,
  UserCheck, Users, DollarSign, Network, ChevronRight, Activity,
} from 'lucide-react'
import {
  LineChart, Line, ResponsiveContainer, Tooltip,
} from 'recharts'
import { dashboardApi } from '@/api/dashboard.api'
import { ticketsApi } from '@/api/tickets.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { humanize } from '@/utils/formatters'
import { nodeHealth, HEALTH_SPINE } from './tree/treeModel'
import { cn } from '@/utils/cn'

const RANGE_OPTIONS = [
  { label: '7d',  days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
] as const

const ACTION_TONE: Record<string, BadgeTone> = {
  comment_posted:            'success',
  held_low_confidence:       'warn',
  abstained_no_kb_coverage:  'warn',
  rejected_by_technician:    'critical',
  rolled_back_by_technician: 'critical',
  halted_kill_switch:        'neutral',
  pipeline_error:            'critical',
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function Spark({ data, color, suffix = '%' }: { data: number[]; color: string; suffix?: string }) {
  const points = data.map((v, i) => ({ i, v }))
  return (
    <ResponsiveContainer width="100%" height={56}>
      <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
        <Tooltip
          contentStyle={{
            background: 'rgb(var(--surface))',
            border: '1px solid rgb(var(--line))',
            borderRadius: 8,
            padding: '4px 8px',
            fontSize: 12,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            color: 'rgb(var(--ink))',
          }}
          labelFormatter={() => ''}
          formatter={(v: number) => [`${Math.round(v)}${suffix}`, '']}
        />
        <Line type="monotone" dataKey="v" stroke={color} dot={false} strokeWidth={2} activeDot={{ r: 4 }} />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function ManagerDashboard() {
  const navigate = useNavigate()
  const [rangeDays, setRangeDays] = useState<number>(30)
  const dateFrom = useMemo(() => isoDaysAgo(rangeDays), [rangeDays])

  const { data: resolution, isLoading: resLoading, isError: resError, refetch: refetchRes } = useQuery({
    queryKey: ['manager', 'resolution', rangeDays],
    queryFn:  () => dashboardApi.getManagerResolution({ date_from: dateFrom }),
    refetchInterval: 60_000,
  })
  const { data: confidence, isLoading: confLoading } = useQuery({
    queryKey: ['manager', 'confidence', rangeDays],
    queryFn:  () => dashboardApi.getManagerConfidence({ date_from: dateFrom }),
    refetchInterval: 60_000,
  })
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['manager', 'tech-stats'],
    queryFn:  dashboardApi.getTechnicianStats,
    refetchInterval: 30_000,
  })
  const { data: sla } = useQuery({
    queryKey: ['manager', 'sla', 'overview', rangeDays],
    queryFn:  () => dashboardApi.getManagerSLA({ date_from: dateFrom }),
    refetchInterval: 60_000,
  })
  const { data: team } = useQuery({
    queryKey: ['manager', 'team', 'overview', rangeDays],
    queryFn:  () => dashboardApi.getManagerTeam({ date_from: dateFrom }),
  })
  const { data: abstention } = useQuery({
    queryKey: ['manager', 'abstention', 'overview', rangeDays],
    queryFn:  () => dashboardApi.getManagerAbstention({ date_from: dateFrom }),
  })
  const { data: collisions } = useQuery({
    queryKey: ['manager', 'collisions', 'overview', rangeDays],
    queryFn:  () => dashboardApi.getManagerCollisions({ date_from: dateFrom }),
  })
  const { data: costSavings } = useQuery({
    queryKey: ['manager', 'cost-savings', 'overview', rangeDays],
    queryFn:  () => dashboardApi.getManagerCostSavings({ date_from: dateFrom }),
  })

  // The Ticket Universe panel — same aggregation the Ticket Tree page uses,
  // rendered flat here as per-category health rows that deep-link into it.
  const { data: tree } = useQuery({
    queryKey: ['manager', 'ticket-tree', 'overview', rangeDays],
    queryFn:  () => dashboardApi.getTicketTree({ date_from: dateFrom }),
    refetchInterval: 60_000,
  })

  // Live activity — newest pipeline outcomes; WS events invalidate ['tickets'].
  const { data: recent } = useQuery({
    queryKey: ['tickets', 'recent-activity'],
    queryFn:  () => ticketsApi.list({ page_size: 8 }),
    refetchInterval: 30_000,
  })

  const loading = resLoading || confLoading || statsLoading

  const autoTrend   = resolution?.trend_data.map((d) => d.auto_pct)  ?? []
  const confTrend   = confidence?.trend_data.map((d) => d.avg_score * 100) ?? []
  const overallConf = confidence?.avg_by_category.length
    ? confidence.avg_by_category.reduce((s, c) => s + c.avg_score, 0) / confidence.avg_by_category.length
    : null

  const slaCompliance = sla?.compliance_by_category.length
    ? sla.compliance_by_category.reduce((s, c) => s + c.compliance_pct, 0) / sla.compliance_by_category.length
    : null
  const upcomingDeadlineCount = sla?.upcoming_deadlines.length ?? 0
  const highAbstentionCount = abstention?.filter((a) => a.gap_severity === 'high').length ?? 0
  const activeCollisionCount = collisions?.collision_events.length ?? 0

  const maxGroupTotal = Math.max(1, ...(tree?.root.groups.map((g) => g.total) ?? [1]))

  return (
    <div className="space-y-5">
      <PageHeader
        title="Command Center"
        description="Live operational picture — pipeline outcomes, SLA health, and where to look next"
        actions={
          <div className="flex items-center gap-1 rounded-lg bg-sunken p-1 shrink-0">
            {RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => setRangeDays(opt.days)}
                className={`px-2.5 py-1 text-xs font-medium font-mono rounded-md transition-colors ${
                  rangeDays === opt.days
                    ? 'bg-surface text-ink shadow-sm'
                    : 'text-faint hover:text-body'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        }
      />

      {resError && <ErrorBanner message="Failed to load resolution analytics." onRetry={() => refetchRes()} />}

      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : (
        <>
          {/* KPI hero */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Auto-Resolution Rate"
              value={`${resolution?.auto_pct ?? 0}%`}
              icon={Zap}
              delta={resolution ? { label: 'of tickets', positive: (resolution.auto_pct ?? 0) >= 70 } : undefined}
            />
            <StatCard
              label="First Contact Rate"
              value={`${resolution?.first_contact_rate ?? 0}%`}
              icon={TrendingUp}
              delta={resolution ? { label: 'resolved on first touch', positive: (resolution.first_contact_rate ?? 0) >= 60 } : undefined}
            />
            <StatCard
              label="Avg Confidence"
              value={overallConf != null ? `${Math.round(overallConf * 100)}%` : '—'}
              icon={Target}
              delta={overallConf != null ? { label: 'across categories', positive: overallConf >= 0.8 } : undefined}
            />
            <button onClick={() => navigate('/manager/sla')} className="text-left">
              <StatCard
                label="SLA Breaches"
                value={stats?.sla_breach_count ?? 0}
                icon={AlertCircle}
                className="transition-colors hover:border-faint/40"
                delta={stats ? { label: 'total breaches', positive: stats.sla_breach_count === 0 } : undefined}
              />
            </button>
          </div>

          {/* Ticket Universe + Live Activity */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="card p-5 lg:col-span-2">
              <div className="flex items-center justify-between mb-1">
                <h2 className="overline-label flex items-center gap-1.5">
                  <Network className="h-3.5 w-3.5" /> Ticket Universe
                </h2>
                <button
                  onClick={() => navigate('/manager/tree')}
                  className="btn-ghost !py-1 !px-2 text-xs"
                >
                  Open full tree <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
              <p className="text-xs text-faint mb-4">
                {tree ? `${tree.root.total} tickets · ${tree.root.auto_resolved} auto-resolved · ${tree.root.breached} SLA breached` : 'Loading…'}
              </p>
              {tree?.root.groups.length ? (
                <div className="space-y-1.5">
                  {tree.root.groups.slice(0, 7).map((g) => (
                    <button
                      key={g.key}
                      onClick={() => navigate(`/manager/tree?expand=${encodeURIComponent(g.key)}`)}
                      className={cn(
                        'w-full flex items-center gap-3 rounded-md bg-sunken px-3 py-2 text-left',
                        'hover:bg-canvas transition-colors group',
                        HEALTH_SPINE[nodeHealth(g)],
                      )}
                    >
                      <span className="text-xs font-medium text-ink w-32 truncate shrink-0" title={g.label}>{g.label}</span>
                      <div className="flex-1 h-1.5 rounded-full bg-line/50 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-accent transition-[width]"
                          style={{ width: `${(g.total / maxGroupTotal) * 100}%` }}
                        />
                      </div>
                      <span className="font-mono text-xs text-body w-8 text-right shrink-0">{g.total}</span>
                      <div className="flex items-center gap-1 w-24 justify-end shrink-0">
                        {g.breached > 0 && <Badge tone="critical" mono>{g.breached}⚠</Badge>}
                        {g.in_review > 0 && <Badge tone="warn" mono>{g.in_review}</Badge>}
                        {g.sla_compliance_pct != null && (
                          <span className="font-mono text-[11px] text-faint">{Math.round(g.sla_compliance_pct)}%</span>
                        )}
                      </div>
                      <ChevronRight className="h-3.5 w-3.5 text-faint opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-faint py-6 text-center">No tickets processed in this window</p>
              )}
            </div>

            {/* Live activity feed */}
            <div className="card p-5">
              <h2 className="overline-label mb-3 flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5" /> Live Activity
              </h2>
              {recent?.items.length ? (
                <div className="space-y-2.5">
                  {recent.items.map((t) => (
                    <div key={t.ticket_id} className="flex items-start justify-between gap-2 text-xs">
                      <div className="min-w-0">
                        <p className="font-mono font-medium text-ink truncate">{t.ticket_id}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <Badge tone={ACTION_TONE[t.action_taken ?? ''] ?? 'neutral'}>
                            {humanize(t.action_taken ?? 'processing')}
                          </Badge>
                          {t.confidence_score != null && (
                            <span className="font-mono text-[10px] text-faint">{Math.round(t.confidence_score * 100)}%</span>
                          )}
                        </div>
                      </div>
                      <span className="text-[10px] text-faint whitespace-nowrap shrink-0 mt-0.5" title={t.category ?? undefined}>
                        {t.category ?? ''}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-faint py-6 text-center">No pipeline activity yet</p>
              )}
            </div>
          </div>

          {/* Trends */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="card p-5">
              <h2 className="overline-label mb-1">Auto-Resolution Trend</h2>
              <p className="text-xs text-faint mb-3">% auto-resolved per day (last {rangeDays} days)</p>
              {autoTrend.length > 1 ? (
                <Spark data={autoTrend} color="#2563eb" />
              ) : (
                <p className="text-sm text-faint py-4 text-center">No trend data yet</p>
              )}
            </div>

            <div className="card p-5">
              <h2 className="overline-label mb-1">Confidence Trend</h2>
              <p className="text-xs text-faint mb-3">Avg confidence score per day (last 30 days)</p>
              {confTrend.length > 1 ? (
                <Spark data={confTrend} color="#059669" />
              ) : (
                <p className="text-sm text-faint py-4 text-center">No trend data yet</p>
              )}
            </div>
          </div>

          {/* Cross-links into the manager detail pages */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <button onClick={() => navigate('/manager/sla')} className="text-left">
              <StatCard
                label="SLA Compliance"
                value={slaCompliance != null ? `${Math.round(slaCompliance)}%` : '—'}
                icon={Target}
                className="transition-colors hover:border-faint/40"
                delta={{ label: `${upcomingDeadlineCount} upcoming`, positive: (slaCompliance ?? 100) >= 90 }}
              />
            </button>
            <button onClick={() => navigate('/manager/team')} className="text-left">
              <StatCard
                label="Team Size"
                value={team?.length ?? '—'}
                icon={UserCheck}
                className="transition-colors hover:border-faint/40"
                delta={team ? { label: 'active technicians', positive: true } : undefined}
              />
            </button>
            <button onClick={() => navigate('/manager/abstention')} className="text-left">
              <StatCard
                label="Abstention Gaps"
                value={highAbstentionCount}
                icon={AlertCircle}
                className="transition-colors hover:border-faint/40"
                delta={abstention ? { label: 'high-severity categories', positive: highAbstentionCount === 0 } : undefined}
              />
            </button>
            <button onClick={() => navigate('/manager/collisions')} className="text-left">
              <StatCard
                label="Collision Events"
                value={activeCollisionCount}
                icon={Users}
                className="transition-colors hover:border-faint/40"
                delta={collisions ? { label: 'concurrent claims', positive: activeCollisionCount === 0 } : undefined}
              />
            </button>
            <button onClick={() => navigate('/manager/savings')} className="text-left">
              <StatCard
                label="Cost Savings"
                value={costSavings ? `$${costSavings.cost_reduction.toLocaleString()}` : '—'}
                icon={DollarSign}
                className="transition-colors hover:border-faint/40"
                delta={costSavings ? { label: `${costSavings.hours_saved}h saved`, positive: true } : undefined}
              />
            </button>
          </div>
        </>
      )}
    </div>
  )
}
