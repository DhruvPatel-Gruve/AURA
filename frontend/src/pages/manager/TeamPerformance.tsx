import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { UserCheck, ArrowUp, ArrowDown } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { dashboardApi } from '@/api/dashboard.api'
import type { ManagerTeamMember } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { cn } from '@/utils/cn'

type SortKey = 'name' | 'ticket_count' | 'correction_rate'

function SortableHeader({
  label, column, sortKey, sortDir, onSort, align = 'left',
}: {
  label:   string
  column:  SortKey
  sortKey: SortKey
  sortDir: 'asc' | 'desc'
  onSort:  (column: SortKey) => void
  align?:  'left' | 'right'
}) {
  const active = sortKey === column
  return (
    <th className={cn('pb-2 text-overline font-medium uppercase text-body', align === 'right' ? 'text-right' : 'text-left')}>
      <button
        onClick={() => onSort(column)}
        className={cn(
          'flex items-center gap-1 hover:text-ink',
          align === 'right' && 'ml-auto',
          active && 'text-ink',
        )}
      >
        {label}
        {active && (sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}

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

function sortMembers(members: ManagerTeamMember[], sortKey: SortKey, sortDir: 'asc' | 'desc'): ManagerTeamMember[] {
  const sorted = [...members].sort((a, b) => {
    if (sortKey === 'name') return a.name.localeCompare(b.name)
    return a[sortKey] - b[sortKey]
  })
  return sortDir === 'asc' ? sorted : sorted.reverse()
}

export default function TeamPerformance() {
  const [search, setSearch]   = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('ticket_count')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data: members, isLoading } = useQuery({
    queryKey: ['manager', 'team'],
    queryFn:  () => dashboardApi.getManagerTeam(),
    refetchInterval: 60_000,
  })

  const handleSort = (column: SortKey) => {
    if (sortKey === column) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(column); setSortDir('asc') }
  }

  const filtered = (members ?? []).filter((m) =>
    m.name.toLowerCase().includes(search.trim().toLowerCase()),
  )
  const visible = sortMembers(filtered, sortKey, sortDir)

  const totalTickets  = members?.reduce((s, m) => s + m.ticket_count, 0) ?? 0
  const avgCorrection = members?.length
    ? members.reduce((s, m) => s + m.correction_rate, 0) / members.length
    : null

  const chartData = members?.map((m) => ({
    name:  m.name.split(' ')[0],
    full:  m.name,
    value: m.ticket_count,
  })) ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Team Performance"
        description="Technician activity, correction rates, and workload distribution"
      />

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Active Technicians"
              value={members?.length ?? 0}
              icon={UserCheck}
            />
            <StatCard
              label="Total Actions"
              value={totalTickets}
              delta={{ label: 'queue items resolved', positive: true }}
            />
            <StatCard
              label="Avg Correction Rate"
              value={avgCorrection != null ? `${avgCorrection.toFixed(1)}%` : '—'}
              delta={avgCorrection != null ? { label: 'edits before posting', positive: avgCorrection <= 20 } : undefined}
            />
          </div>

          {/* Bar chart */}
          <div className="card p-5">
            <h2 className="overline-label mb-4">Tickets Resolved per Technician</h2>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                  <XAxis dataKey="name" tick={AXIS_TICK} />
                  <YAxis tick={AXIS_TICK} allowDecimals={false} />
                  <Tooltip
                    {...TOOLTIP_STYLE}
                    formatter={(v: number, _: string, props: { payload?: { full?: string } }) => [v, props?.payload?.full ?? 'Tickets']}
                  />
                  <Bar dataKey="value" fill="#2563eb" radius={[4, 4, 0, 0]} maxBarSize={48} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-faint text-center py-12">
                No technician data yet — activity will appear once technicians process queue items
              </p>
            )}
          </div>

          {/* Table */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="overline-label">Technician Breakdown</h2>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name…"
                className="input-base w-56 text-sm"
              />
            </div>
            {members?.length ? (
              visible.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line">
                      <SortableHeader label="Name" column="name" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                      <SortableHeader label="Tickets" column="ticket_count" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="right" />
                      <SortableHeader label="Correction Rate" column="correction_rate" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="right" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {visible.map((m) => (
                      <tr key={m.technician_id} className="hover:bg-sunken">
                        <td className="py-2.5 font-medium text-ink">{m.name}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-body">{m.ticket_count}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums">
                          <span className={
                            m.correction_rate > 30
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-body'
                          }>
                            {m.correction_rate.toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              ) : (
                <p className="text-sm text-faint py-6 text-center">No technicians match "{search}"</p>
              )
            ) : (
              <p className="text-sm text-faint">No technicians found</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
