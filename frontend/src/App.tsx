import { lazy, Suspense, useEffect, useRef } from 'react'
import { Routes, Route, Navigate, BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useConfigStore } from '@/store/configStore'
import { useAuthStore } from '@/store/authStore'
import { wireAuthToClient } from '@/api/client'
import { apiClient } from '@/api/client'
import { setupApi } from '@/api/setup.api'

// Layout
import { AppShell } from '@/components/layout/AppShell'

// Guards
import { RoleGuard } from '@/router/index'

// Pages
import Login from '@/pages/Login'
import SetupWizard from '@/pages/admin/SetupWizard'

// Master admin pages
import TenantManagement  from '@/pages/master/TenantManagement'

// Admin pages
import AdminDashboard    from '@/pages/admin/AdminDashboard'
import UserManagement    from '@/pages/admin/UserManagement'
import CategoryManagement from '@/pages/admin/CategoryManagement'
import AgentConfig       from '@/pages/admin/AgentConfig'
import Integrations      from '@/pages/admin/Integrations'
import KillSwitch        from '@/pages/admin/KillSwitch'
import RollbackHistory   from '@/pages/admin/RollbackHistory'
import AuditLog          from '@/pages/admin/AuditLog'
import QdrantIndex       from '@/pages/admin/QdrantIndex'
import SystemHealth      from '@/pages/admin/SystemHealth'

// Manager pages
import ManagerDashboard    from '@/pages/manager/ManagerDashboard'
import SLACompliance       from '@/pages/manager/SLACompliance'
import ResolutionAnalytics from '@/pages/manager/ResolutionAnalytics'
import ConfidenceAnalytics from '@/pages/manager/ConfidenceAnalytics'
import TeamPerformance     from '@/pages/manager/TeamPerformance'
import AbstentionReport    from '@/pages/manager/AbstentionReport'
import CollisionLog        from '@/pages/manager/CollisionLog'
import ApprovalQueue       from '@/pages/manager/ApprovalQueue'

// Technician pages
import TechnicianDashboard  from '@/pages/technician/TechnicianDashboard'
import TicketQueue           from '@/pages/technician/TicketQueue'

// End User pages (Layer 6)
import EndUserDashboard    from '@/pages/enduser/EndUserDashboard'
import MyTickets           from '@/pages/enduser/MyTickets'
import SubmitTicket        from '@/pages/enduser/SubmitTicket'
import LiveChat            from '@/pages/enduser/LiveChat'

import { LoadingSpinner } from '@/components/ui/LoadingSpinner'

// Code-split: React Flow + framer-motion only load when a manager opens the
// tree, keeping the main bundle lean for every other role.
const TicketTree = lazy(() => import('@/pages/manager/TicketTree'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

function AppRoutes() {
  const { initTheme, setupComplete, setSetupComplete, setCompanyBranding, clearBranding, setItsmProvider } = useConfigStore()
  const { accessToken, role } = useAuthStore()
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Wire auth helpers to axios interceptor (once, on mount)
  useEffect(() => {
    wireAuthToClient({
      getToken:  () => useAuthStore.getState().accessToken,
      setToken:  (t) => useAuthStore.getState().setToken(t),
      clearAuth: () => useAuthStore.getState().clearAuth(),
      navigate:  (path) => window.location.replace(path),
    })
    initTheme()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fetch company branding whenever the user logs in or refreshes while authenticated.
  // master_admin has no tenant_id and manages no single tenant's identity — it always
  // gets the generic AURA look, never a tenant's logo/name/accent.
  useEffect(() => {
    if (!accessToken) return
    if (role === 'master_admin') {
      clearBranding()
      return
    }
    apiClient
      .get<{ company_name: string | null; company_logo: string | null; accent_color: string | null; itsm_provider?: string }>('/admin/branding')
      .then(({ data }) => {
        setCompanyBranding(data.company_name ?? '', data.company_logo ?? '', data.accent_color ?? '')
        setItsmProvider(data.itsm_provider === 'zendesk' ? 'zendesk' : 'jira')
      })
      .catch(() => { /* backend not yet configured — silent */ })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, role])

  // Check setup status once a session exists — /setup/status now requires
  // auth (setup is per-tenant), so there's nothing to check pre-login.
  // Login itself already sets setupComplete from the login response; this
  // effect only matters for a returning user who reloads with a persisted
  // token. Retries every 3s until the backend responds.
  useEffect(() => {
    if (!accessToken) return

    let cancelled = false

    const attempt = () => {
      setupApi
        .getStatus()
        .then((s) => { if (!cancelled) setSetupComplete(s.setup_complete) })
        .catch(() => {
          if (!cancelled) retryRef.current = setTimeout(attempt, 3000)
        })
    }

    attempt()
    return () => {
      cancelled = true
      if (retryRef.current) clearTimeout(retryRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken])

  // Only block rendering on the setup check when there's actually a session
  // to check it for — an anonymous visitor must always be able to reach
  // /login without waiting on a request /setup/status would 401 on.
  if (accessToken && setupComplete === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<Login />} />

      {/* Setup — only when setup is incomplete */}
      {!setupComplete && (
        <Route path="/setup" element={<SetupWizard onLaunch={() => setSetupComplete(true)} />} />
      )}

      {/* If setup not complete, redirect everything to /setup or /login */}
      {!setupComplete && (
        <Route path="*" element={
          accessToken ? <Navigate to="/setup" replace /> : <Navigate to="/login" replace />
        } />
      )}

      {/* Master admin routes — tenant provisioning only, no ticket/audit data */}
      <Route element={<RoleGuard required="master_admin" />}>
        <Route element={<AppShell />}>
          <Route path="/master" element={<TenantManagement />} />
        </Route>
      </Route>

      {/* Admin routes */}
      <Route element={<RoleGuard required="admin" />}>
        <Route element={<AppShell />}>
          <Route path="/admin"               element={<AdminDashboard />} />
          <Route path="/admin/users"         element={<UserManagement />} />
          <Route path="/admin/categories"    element={<CategoryManagement />} />
          <Route path="/admin/config"        element={<AgentConfig />} />
          <Route path="/admin/integrations"  element={<Integrations />} />
          <Route path="/admin/kill-switch"   element={<KillSwitch />} />
          <Route path="/admin/rollback"      element={<RollbackHistory />} />
          <Route path="/admin/audit-log"     element={<AuditLog />} />
          <Route path="/admin/qdrant"        element={<QdrantIndex />} />
          <Route path="/admin/health"        element={<SystemHealth />} />
        </Route>
      </Route>

      {/* Manager routes */}
      <Route element={<RoleGuard required="manager" />}>
        <Route element={<AppShell />}>
          <Route path="/manager"               element={<ManagerDashboard />} />
          <Route path="/manager/tree"          element={
            <Suspense fallback={<div className="flex justify-center py-20"><LoadingSpinner size="lg" /></div>}>
              <TicketTree />
            </Suspense>
          } />
          <Route path="/manager/sla"           element={<SLACompliance />} />
          <Route path="/manager/resolution"    element={<ResolutionAnalytics />} />
          <Route path="/manager/confidence"    element={<ConfidenceAnalytics />} />
          <Route path="/manager/team"          element={<TeamPerformance />} />
          <Route path="/manager/abstention"    element={<AbstentionReport />} />
          <Route path="/manager/collisions"    element={<CollisionLog />} />
          <Route path="/manager/approvals"     element={<ApprovalQueue />} />
        </Route>
      </Route>

      {/* Technician routes */}
      <Route element={<RoleGuard required="technician" />}>
        <Route element={<AppShell />}>
          <Route path="/technician"                       element={<TechnicianDashboard />} />
          <Route path="/technician/queue"                 element={<TicketQueue />} />
          {/* Folded into the unified Tickets page — redirect any old bookmarks/links */}
          <Route path="/technician/low-confidence"        element={<Navigate to="/technician/queue?filter=needs-review" replace />} />
        </Route>
      </Route>

      {/* End User routes */}
      <Route element={<RoleGuard required="enduser" />}>
        <Route element={<AppShell />}>
          <Route path="/enduser"         element={<EndUserDashboard />} />
          <Route path="/enduser/tickets" element={<MyTickets />} />
          <Route path="/enduser/submit"  element={<SubmitTicket />} />
          <Route path="/enduser/chat"    element={<LiveChat />} />
        </Route>
      </Route>

      {/* Root redirect */}
      <Route path="/" element={
        accessToken && role
          ? <Navigate to={`/${role}`} replace />
          : <Navigate to="/login" replace />
      } />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
