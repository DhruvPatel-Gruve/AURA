import { useQuery } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { dashboardApi } from '@/api/dashboard.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatDateTime } from '@/utils/formatters'

export default function CollisionLog() {
  const { data, isLoading } = useQuery({
    queryKey: ['manager', 'collisions'],
    queryFn:  () => dashboardApi.getManagerCollisions(),
    refetchInterval: 60_000,
  })

  const collisionCount = data?.collision_events.length ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        title="Collision Log"
        description="Tickets claimed by multiple technicians simultaneously"
      />

      {isLoading ? (
        <div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard
              label="Collision Events"
              value={collisionCount}
              icon={Users}
              delta={{ label: 'concurrent claims', positive: collisionCount === 0 }}
            />
          </div>

          <div className="card p-5">
            <div className="flex items-baseline gap-2 mb-3">
              <h2 className="overline-label">Collision Events</h2>
              <span className="text-xs text-faint">
                Tickets claimed by multiple technicians simultaneously
              </span>
            </div>
            {data?.collision_events.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line">
                      <th className="text-left pb-2 text-overline font-medium uppercase text-body">Ticket</th>
                      <th className="text-left pb-2 text-overline font-medium uppercase text-body">Claimants</th>
                      <th className="text-left pb-2 text-overline font-medium uppercase text-body">Time</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.collision_events.map((e) => (
                      <tr key={e.ticket_id} className="hover:bg-sunken">
                        <td className="py-2.5 font-mono text-xs text-body">{e.ticket_id}</td>
                        <td className="py-2.5 text-body text-xs">{e.claimants.join(', ')}</td>
                        <td className="py-2.5 font-mono text-faint text-xs whitespace-nowrap">
                          {formatDateTime(e.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-emerald-600 dark:text-emerald-400">No collision events recorded</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
