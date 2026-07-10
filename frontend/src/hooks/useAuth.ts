import { useAuthStore } from '@/store/authStore'
import { useConfigStore } from '@/store/configStore'
import { authApi } from '@/api/auth.api'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

export function useAuth() {
  const { userId, email, displayName, role, accessToken, clearAuth } = useAuthStore()
  const { setKillSwitch } = useConfigStore()
  const queryClient = useQueryClient()
  const navigate    = useNavigate()

  const logout = async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    clearAuth()
    setKillSwitch(false)
    queryClient.clear()
    navigate('/login', { replace: true })
  }

  return {
    userId,
    email,
    displayName,
    role,
    accessToken,
    isAuthenticated: !!accessToken,
    logout,
  }
}
