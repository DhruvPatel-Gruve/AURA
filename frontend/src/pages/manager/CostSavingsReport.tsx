import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { dashboardApi } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
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

export default function CostSavingsReport() {
  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'cost-savings'],
    queryFn:  () => dashboardApi.getManagerCostSavings(),
    refetchInterval: 60_000,
  })

  return (
    <div className="space-y-5">
      <PageHeader
        title="Cost Savings Report"
        description="Estimated savings from AURA's zero-touch resolutions (30 min saved @ $50/hr per ticket)"
      />

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="card p-5">
              <p className="overline-label">Hours Saved</p>
              <p className="mt-1 font-display font-semibold tabular-nums text-3xl text-ink">
                {data ? `${data.hours_saved.toLocaleString()}h` : '—'}
              </p>
              <p className="mt-1 text-xs text-faint">technician hours</p>
            </div>
            <div className="card p-5">
              <p className="overline-label">Cost Reduction</p>
              <p className="mt-1 font-display font-semibold tabular-nums text-3xl text-ink">
                {data ? `$${data.cost_reduction.toLocaleString()}` : '—'}
              </p>
              <p className="mt-1 text-xs text-faint">estimated savings</p>
            </div>
            <div className="card p-5">
              <p className="overline-label">Avg Zero-Touch / Week</p>
              <p className="mt-1 font-display font-semibold tabular-nums text-3xl text-ink">
                {data ? data.zero_touch_per_week.toFixed(1) : '—'}
              </p>
              <p className="mt-1 text-xs text-faint">tickets auto-resolved</p>
            </div>
          </div>

          <div className="card p-4 spine-agent">
            <p className="text-sm text-body">
              <strong className="text-ink">Methodology:</strong> Each zero-touch resolution (AURA handled without technician edit) is estimated
              to save 30 minutes of technician time at $50/hr, saving $25 per ticket.
              Abstained tickets are excluded.
            </p>
          </div>

          <div className="card p-5">
            <h2 className="overline-label mb-4">Weekly Zero-Touch Trend</h2>
            {data?.trend_data.length && data.trend_data.length > 1 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={data.trend_data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'rgb(var(--faint))' }} />
                  <YAxis tick={AXIS_TICK} allowDecimals={false} />
                  <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => [v, 'Zero-Touch Tickets']} />
                  <Bar dataKey="zero_touch" fill="#059669" radius={[4, 4, 0, 0]} maxBarSize={48} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-faint text-center py-12">
                Weekly trend will appear after several weeks of data
              </p>
            )}
          </div>

          {data && data.hours_saved === 0 && (
            <div className="card p-5">
              <p className="text-sm text-faint text-center">
                No zero-touch resolutions recorded yet. Once AURA begins auto-resolving tickets,
                cost savings will be calculated here.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
