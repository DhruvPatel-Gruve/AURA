import { useQuery } from '@tanstack/react-query'
import { TrendingUp } from 'lucide-react'
import {
  PieChart, Pie, Cell, Tooltip,
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer,
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

export default function ResolutionAnalytics() {
  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'resolution'],
    queryFn:  () => dashboardApi.getManagerResolution(),
    refetchInterval: 60_000,
  })

  const pieData = [
    { name: 'Auto-Resolved', value: data?.auto_pct ?? 0, color: '#059669' },
    { name: 'Manual',         value: data?.manual_pct ?? 0, color: 'rgb(var(--line))' },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        title="Resolution Analytics"
        description="Auto-resolution rates and first-contact resolution trends"
      />

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Auto-Resolution"
              value={`${data?.auto_pct ?? 0}%`}
              icon={TrendingUp}
              delta={{ label: 'AURA handled', positive: (data?.auto_pct ?? 0) >= 70 }}
            />
            <StatCard
              label="Manual Resolution"
              value={`${data?.manual_pct ?? 0}%`}
              delta={{ label: 'required human', positive: (data?.manual_pct ?? 0) <= 30 }}
            />
            <StatCard
              label="First Contact Rate"
              value={`${data?.first_contact_rate ?? 0}%`}
              delta={{ label: 'resolved on first touch', positive: (data?.first_contact_rate ?? 0) >= 60 }}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Pie chart */}
            <div className="card p-5">
              <h2 className="overline-label mb-4">Resolution Split</h2>
              {(data?.auto_pct ?? 0) + (data?.manual_pct ?? 0) > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={90}
                      dataKey="value"
                      label={({ name, value }) => `${name}: ${value}%`}
                      labelLine={false}
                    >
                      {pieData.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [`${v}%`]} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-faint text-center py-12">No tickets processed yet</p>
              )}
            </div>

            {/* Trend line */}
            <div className="card p-5">
              <h2 className="overline-label mb-4">Auto-Resolution Trend</h2>
              {data?.trend_data.length && data.trend_data.length > 1 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={data.trend_data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'rgb(var(--faint))' }} tickFormatter={(v) => v.slice(5)} />
                    <YAxis domain={[0, 100]} tick={AXIS_TICK} unit="%" />
                    <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [`${v}%`, 'Auto %']} />
                    <Line type="monotone" dataKey="auto_pct" stroke="#059669" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-faint text-center py-12">
                  Trend data will appear once multiple days of tickets are processed
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
