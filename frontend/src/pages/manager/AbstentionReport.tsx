import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts'
import { dashboardApi } from '@/api/dashboard.api'
import type { ManagerAbstentionItem } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { Badge } from '@/components/ui/Badge'
import type { BadgeTone } from '@/components/ui/Badge'

const TOOLTIP_STYLE = {
  contentStyle: {
    background: 'rgb(var(--surface))',
    border: '1px solid rgb(var(--line))',
    borderRadius: '8px',
    fontSize: '12px',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: 'rgb(var(--ink))',
  },
}

const AXIS_TICK = { fontSize: 11, fill: 'rgb(var(--faint))' }

const SEVERITY_TONE: Record<ManagerAbstentionItem['gap_severity'], BadgeTone> = {
  low:    'success',
  medium: 'warn',
  high:   'critical',
}

const SEVERITY_COLOR: Record<ManagerAbstentionItem['gap_severity'], string> = {
  low:    '#059669',
  medium: '#d97706',
  high:   '#dc2626',
}

export default function AbstentionReport() {
  const navigate = useNavigate()
  const [sortBy, setSortBy] = useState<'rate' | 'count'>('rate')

  const drillToTree = (category: string) =>
    navigate(`/manager/tree?expand=${encodeURIComponent(category)}`)

  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'abstention', sortBy],
    queryFn:  () => dashboardApi.getManagerAbstention({ sort_by: sortBy }),
    refetchInterval: 60_000,
  })

  const avgRate = data?.length
    ? data.reduce((s, c) => s + c.abstention_rate, 0) / data.length
    : null
  const highSeverity = data?.filter((c) => c.gap_severity === 'high').length ?? 0

  const chartData = data?.map((c) => ({
    name:     c.category.length > 14 ? c.category.slice(0, 14) + '…' : c.category,
    full:     c.category,
    value:    c.abstention_rate,
    severity: c.gap_severity,
  })) ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Abstention Report"
        description="Categories where AURA declined to answer — knowledge gaps to address"
      />

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="card p-4 spine-warn">
            <p className="text-sm text-body">
              <strong className="text-ink">What is abstention?</strong> AURA abstains when its confidence is below the abstention threshold.
              High abstention in a category means the knowledge base needs more resolved tickets for that topic.
            </p>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Avg Abstention Rate"
              value={avgRate != null ? `${avgRate.toFixed(1)}%` : '—'}
              icon={AlertCircle}
              delta={avgRate != null ? { label: 'across categories', positive: avgRate < 15 } : undefined}
            />
            <StatCard
              label="High-Gap Categories"
              value={highSeverity}
              delta={{ label: 'need knowledge base attention', positive: highSeverity === 0 }}
            />
            <StatCard
              label="Categories Monitored"
              value={data?.length ?? 0}
            />
          </div>

          {/* Chart */}
          <div className="card p-5">
            <h2 className="overline-label mb-4">Abstention Rate by Category</h2>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                  <XAxis dataKey="name" tick={AXIS_TICK} />
                  <YAxis domain={[0, 100]} tick={AXIS_TICK} unit="%" />
                  <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [`${v}%`, 'Abstention Rate']} />
                  <ReferenceLine y={30} stroke="#dc2626" strokeDasharray="4 4" label={{ value: 'High (30%)', position: 'right', fontSize: 10, fill: '#dc2626' }} />
                  <ReferenceLine y={10} stroke="#d97706" strokeDasharray="4 4" label={{ value: 'Medium (10%)', position: 'right', fontSize: 10, fill: '#d97706' }} />
                  <Bar
                    dataKey="value"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={48}
                    className="cursor-pointer"
                    onClick={(d) => {
                      const e = (d as { full?: string; payload?: { full?: string } })
                      const cat = e.full ?? e.payload?.full
                      if (cat) drillToTree(cat)
                    }}
                  >
                    {chartData.map((entry) => (
                      <Cell key={entry.name} fill={SEVERITY_COLOR[entry.severity]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-faint text-center py-12">No abstention data yet</p>
            )}
          </div>

          {/* Table */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="overline-label">Category Detail</h2>
              <div className="flex gap-1 p-1 bg-sunken rounded-lg w-fit">
                {(['rate', 'count'] as const).map((opt) => (
                  <button
                    key={opt}
                    onClick={() => setSortBy(opt)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                      sortBy === opt ? 'bg-surface text-ink shadow-sm' : 'text-faint hover:text-body'
                    }`}
                  >
                    Sort by {opt === 'rate' ? 'rate' : 'raw count'}
                  </button>
                ))}
              </div>
            </div>
            {data?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line">
                      <th className="text-left pb-2 text-overline font-medium uppercase text-body">Category</th>
                      <th className="text-right pb-2 text-overline font-medium uppercase text-body">Abstention Rate</th>
                      <th className="text-right pb-2 text-overline font-medium uppercase text-body">Abstained</th>
                      <th className="text-right pb-2 text-overline font-medium uppercase text-body">Severity</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.map((c) => (
                      <tr
                        key={c.category}
                        className="hover:bg-sunken cursor-pointer"
                        onClick={() => drillToTree(c.category)}
                        title="Open in Ticket Tree"
                      >
                        <td className="py-2.5 text-ink">{c.category}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-body">
                          {c.abstention_rate.toFixed(1)}%
                        </td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-faint">
                          {c.abstained_count}
                        </td>
                        <td className="py-2.5 text-right">
                          <Badge tone={SEVERITY_TONE[c.gap_severity]} dot>
                            {c.gap_severity}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-emerald-600 dark:text-emerald-400">No abstentions recorded</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
