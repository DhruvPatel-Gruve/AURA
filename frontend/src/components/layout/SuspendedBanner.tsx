import { AlertTriangle } from 'lucide-react'
import { useConfigStore } from '@/store/configStore'

export function SuspendedBanner() {
  const active = useConfigStore((s) => s.killSwitchActive)
  if (!active) return null

  return (
    <div className="w-full flex items-center justify-center gap-2.5
                    bg-red-700 text-white text-sm py-2 px-4 shrink-0">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="font-mono text-xs font-medium tracking-wide">SUSPENDED</span>
      <span className="text-red-100">— all automated processing is halted. Contact your administrator.</span>
    </div>
  )
}
