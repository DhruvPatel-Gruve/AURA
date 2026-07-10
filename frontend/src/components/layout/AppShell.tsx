import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { SuspendedBanner } from './SuspendedBanner'
import { ToastContainer } from '@/components/ui/ToastContainer'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useConfigStore } from '@/store/configStore'
import { cn } from '@/utils/cn'

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const killSwitchActive = useConfigStore((s) => s.killSwitchActive)

  // Establish WebSocket connection for this session
  useWebSocket()

  return (
    <div className="flex h-screen overflow-hidden">
      <ToastContainer />
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />

      <div className="flex flex-col flex-1 min-w-0">
        {/* Suspended banner shifts the content down by its height (32px) */}
        {killSwitchActive && <SuspendedBanner />}
        <TopBar />

        <main
          className={cn(
            'flex-1 overflow-y-auto',
            'bg-canvas',
            'px-6 py-5',
          )}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}
