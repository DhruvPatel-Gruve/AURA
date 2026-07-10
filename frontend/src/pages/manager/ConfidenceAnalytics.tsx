import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart2 } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  LineChart, Line, ResponsiveContainer, Cell,
} from 'recharts'
import { dashboardApi } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'

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

export default function ConfidenceAnalytics() {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'confidence'],
    queryFn:  () => dashboardApi.getManagerConfidence(),
    refetchInterval: 60_000,
  })

  const avgConfidence = data?.avg_by_category.length
    ? data.avg_by_category.reduce((s, c) => s + c.avg_score, 0) / data.avg_by_category.length
    : null

  const barData = data?.avg_by_category.map((c) => ({
    name:  c.category.length > 14 ? c.category.slice(0, 14) + '…' : c.category,
    full:  c.category,
    value: Math.round(c.avg_score * 100),
  })) ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Confidence Analytics"
        description="AURA's confidence scores by category and over time"
      />

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Overall Avg Confidence"
              value={avgConfidence != null ? `${Math.round(avgConfidence * 100)}%` : '—'}
              icon={BarChart2}
              delta={avgConfidence != null ? { label: 'across all categories', positive: avgConfidence >= 0.8 } : undefined}
            />
            <StatCard
              label="Categories Tracked"
              value={data?.avg_by_category.length ?? 0}
            />
            <StatCard
              label="Highest Confidence"
              value={data?.avg_by_category[0]
                ? `${Math.round(data.avg_by_category[0].avg_score * 100)}%`
                : '—'}
              delta={data?.avg_by_category[0]
                ? { label: data.avg_by_category[0].category, positive: true }
                : undefined}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Avg by category */}
            <div className="card p-5">
              <h2 className="overline-label mb-4">Avg Confidence by Category</h2>
              {barData.length > 0 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={barData} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} tick={AXIS_TICK} unit="%" />
                    <YAxis type="category" dataKey="name" tick={AXIS_TICK} width={90} />
                    <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [`${v}%`, 'Avg Confidence']} />
                    <Bar
                      dataKey="value"
                      radius={[0, 4, 4, 0]}
                      maxBarSize={20}
                      className="cursor-pointer"
                      onClick={(d) => {
                        const e = (d as { full?: string; payload?: { full?: string } })
                        const cat = e.full ?? e.payload?.full
                        if (cat) navigate(`/manager/tree?expand=${encodeURIComponent(cat)}`)
                      }}
                    >
                      {barData.map((entry) => (
                        <Cell
                          key={entry.name}
                          fill={entry.value >= 80 ? '#059669' : entry.value >= 60 ? '#d97706' : '#dc2626'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-faint text-center py-12">No confidence data yet</p>
              )}
            </div>

            {/* Distribution histogram */}
            <div className="card p-5">
              <h2 className="overline-label mb-4">Score Distribution</h2>
              {data?.histogram_buckets.some((b) => b.count > 0) ? (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={data.histogram_buckets} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                    <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: 'rgb(var(--faint))' }} interval={0} angle={-30} textAnchor="end" height={44} />
                    <YAxis tick={AXIS_TICK} />
                    <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [v, 'Tickets']} />
                    <Bar dataKey="count" fill="#2563eb" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-faint text-center py-12">No distribution data yet</p>
              )}
            </div>
          </div>

          {/* Trend */}
          <div className="card p-5">
            <h2 className="overline-label mb-4">Confidence Trend (30 days)</h2>
            {data?.trend_data.length && data.trend_data.length > 1 ? (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={data.trend_data.map((d) => ({ ...d, pct: Math.round(d.avg_score * 100) }))} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'rgb(var(--faint))' }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis domain={[0, 100]} tick={AXIS_TICK} unit="%" />
                  <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [`${v}%`, 'Avg Confidence']} />
                  <Line type="monotone" dataKey="pct" stroke="#059669" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-faint text-center py-8">
                Trend data will appear after multiple days of processing
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
