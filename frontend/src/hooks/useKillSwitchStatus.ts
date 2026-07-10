import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '@/api/admin.api'
import { useConfigStore } from '@/store/configStore'

export function useKillSwitchStatus() {
  const setKillSwitch = useConfigStore((s) => s.setKillSwitch)

  const query = useQuery({
    queryKey: ['admin', 'kill-switch'],
    queryFn:  adminApi.getKillSwitch,
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (query.data != null) {
      // backend: enabled=true means aura_enabled=true (AURA running) → kill switch OFF
      setKillSwitch(!query.data.enabled)
    }
  }, [query.data, setKillSwitch])

  return query
}
