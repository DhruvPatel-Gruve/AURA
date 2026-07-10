import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Target, AlertTriangle, Clock } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { dashboardApi } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatDateTime } from '@/utils/formatters'

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

export default function SLACompliance() {
  const navigate = useNavigate()
  const [category, setCategory] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'sla', category, dateFrom, dateTo],
    queryFn:  () => dashboardApi.getManagerSLA({
      category: category || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    }),
    refetchInterval: 60_000,
  })

  // Accumulate known categories across fetches so the dropdown doesn't lose
  // options once a category filter narrows the result set.
  const [knownCategories, setKnownCategories] = useState<string[]>([])
  useEffect(() => {
    if (!data) return
    const seen = new Set(knownCategories)
    let changed = false
    for (const c of data.compliance_by_category) {
      if (c.category && !seen.has(c.category)) { seen.add(c.category); changed = true }
    }
    if (changed) setKnownCategories(Array.from(seen).sort())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const avgCompliance = data?.compliance_by_category.length
    ? Math.round(data.compliance_by_category.reduce((s, c) => s + c.compliance_pct, 0) / data.compliance_by_category.length)
    : null

  const chartData = data?.compliance_by_category.map((c) => ({
    name:  c.category.length > 14 ? c.category.slice(0, 14) + '…' : c.category,
    full:  c.category,
    value: c.compliance_pct,
  })) ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="SLA Compliance"
        description="Compliance rates, breach history and upcoming deadlines"
      />

      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="input-base w-44 text-sm"
        >
          <option value="">All categories</option>
          {knownCategories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="input-base text-sm" />
        <span className="text-xs text-faint">to</span>
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="input-base text-sm" />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Avg Compliance"
              value={avgCompliance != null ? `${avgCompliance}%` : '—'}
              icon={Target}
              delta={avgCompliance != null ? { label: 'across categories', positive: avgCompliance >= 90 } : undefined}
            />
            <StatCard
              label="Total Breaches"
              value={data?.breach_history.length ?? 0}
              icon={AlertTriangle}
              delta={{ label: 'all time', positive: (data?.breach_history.length ?? 0) === 0 }}
            />
            <StatCard
              label="Upcoming Deadlines"
              value={data?.upcoming_deadlines.length ?? 0}
              icon={Clock}
            />
          </div>

          {/* Compliance chart — click a bar to open that category in the Ticket Tree */}
          <div className="card p-5">
            <h2 className="overline-label mb-4">Compliance by Category <span className="normal-case text-faint font-normal">· click a bar to drill into the tree</span></h2>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                  <XAxis dataKey="name" tick={AXIS_TICK} />
                  <YAxis domain={[0, 100]} tick={AXIS_TICK} unit="%" />
                  <Tooltip
                    {...TOOLTIP_STYLE}
                    formatter={(v: number, _: string, props: { payload?: { full?: string } }) => [
                      `${v}%`,
                      props?.payload?.full ?? 'Compliance',
                    ]}
                  />
                  <ReferenceLine y={90} stroke="#dc2626" strokeDasharray="4 4" label={{ value: '90%', position: 'right', fontSize: 10, fill: '#dc2626' }} />
                  <Bar
                    dataKey="value"
                    fill="#2563eb"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={48}
                    className="cursor-pointer"
                    onClick={(d) => {
                      const full = (d as { full?: string; payload?: { full?: string } })
                      const cat = full.full ?? full.payload?.full
                      if (cat) navigate(`/manager/tree?expand=${encodeURIComponent(cat)}`)
                    }}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-faint text-center py-8">No SLA data yet</p>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Breach history */}
            <div className="card p-5">
              <h2 className="overline-label mb-3">Recent Breaches</h2>
              {data?.breach_history.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-line">
                        <th className="text-left pb-2 text-overline font-medium uppercase text-body">Ticket</th>
                        <th className="text-left pb-2 text-overline font-medium uppercase text-body">Category</th>
                        <th className="text-left pb-2 text-overline font-medium uppercase text-body">Breached At</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {data.breach_history.map((b) => (
                        <tr key={b.ticket_id} className="hover:bg-sunken">
                          <td className="py-2 font-mono text-body">{b.ticket_id}</td>
                          <td className="py-2 text-body">{b.category}</td>
                          <td className="py-2 font-mono text-faint whitespace-nowrap">{formatDateTime(b.breached_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-emerald-600 dark:text-emerald-400">No SLA breaches recorded</p>
              )}
            </div>

            {/* Upcoming deadlines */}
            <div className="card p-5">
              <h2 className="overline-label mb-3">Upcoming Deadlines</h2>
              {data?.upcoming_deadlines.length ? (
                <div className="space-y-2">
                  {data.upcoming_deadlines.map((d) => (
                    <div key={d.ticket_id} className="flex items-center justify-between text-xs p-2 rounded-md bg-sunken spine-warn">
                      <div>
                        <span className="font-mono text-body">{d.ticket_id}</span>
                        <span className="ml-2 text-faint">{d.category}</span>
                      </div>
                      <span className="font-mono text-amber-700 dark:text-amber-400 whitespace-nowrap ml-2">
                        {formatDateTime(d.deadline)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-emerald-600 dark:text-emerald-400">No upcoming SLA deadlines</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
