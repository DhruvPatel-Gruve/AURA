import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { ROLE_HOME } from '@/utils/constants'
import type { Role } from '@/utils/constants'

// ── RoleGuard: require specific role ─────────────────────────────────────────
interface RoleGuardProps {
  required: Role
}

export function RoleGuard({ required }: RoleGuardProps) {
  const { accessToken, role } = useAuthStore()

  if (!accessToken) return <Navigate to="/login" replace />
  if (role !== required) return <Navigate to={ROLE_HOME[role!] ?? '/login'} replace />
  return <Outlet />
}
