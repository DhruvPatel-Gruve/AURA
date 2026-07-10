import { useState, type FormEvent } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import { authApi } from '@/api/auth.api'
import { useAuthStore } from '@/store/authStore'
import { useConfigStore } from '@/store/configStore'
import { ROLE_HOME } from '@/utils/constants'
import type { Role } from '@/utils/constants'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'

export default function Login() {
  const { setAuth, accessToken, role } = useAuthStore()
  const { setSetupComplete, setupComplete } = useConfigStore()
  const navigate = useNavigate()

  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  // Already authenticated — redirect (respect setup state)
  if (accessToken && role) {
    const dest = setupComplete === false ? '/setup' : (ROLE_HOME[role as Role] ?? '/')
    return <Navigate to={dest} replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const data = await authApi.login({ email, password })
      setAuth({
        accessToken: data.access_token,
        role:        data.role,
        userId:      data.user_id,
        email,
      })
      setSetupComplete(data.setup_complete)

      // Fetch display name in background
      authApi.me().then((me) => useAuthStore.getState().setAuth({
        accessToken: data.access_token,
        role:        data.role,
        userId:      data.user_id,
        email,
        displayName: me.display_name,
        teamId:      me.team_id,
      })).catch(() => {})

      if (!data.setup_complete) {
        navigate('/setup', { replace: true })
      } else {
        navigate(ROLE_HOME[data.role as Role] ?? '/', { replace: true })
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Invalid email or password'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas px-4">
      <div className="relative w-full max-w-sm">
        <h1 className="font-display text-2xl font-semibold text-ink text-center mb-6 tracking-tight">
          AURA
        </h1>

        {/* Card */}
        <div className="bg-surface border border-line rounded-lg shadow-card p-6">
          <h2 className="text-base font-semibold text-ink mb-5">
            Sign in to your workspace
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-body mb-1.5">
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-base"
                placeholder="admin@company.com"
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-body mb-1.5">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPw ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-base pr-10"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-body"
                  tabIndex={-1}
                >
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20
                            border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full mt-1"
            >
              {loading ? <LoadingSpinner size="sm" /> : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-faint mt-6">
          AURA — IT Resolution Platform
        </p>
      </div>
    </div>
  )
}
