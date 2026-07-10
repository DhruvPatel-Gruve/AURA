import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  withCredentials: true,   // sends httpOnly refresh_token cookie
  headers: { 'Content-Type': 'application/json' },
})

// Lazy import to avoid circular deps — store reads token, refresh posts to /auth/refresh
let _getToken: (() => string | null) | null = null
let _setToken: ((t: string) => void) | null = null
let _clearAuth: (() => void) | null = null
let _navigate:  ((path: string) => void) | null = null

export function wireAuthToClient(opts: {
  getToken:  () => string | null
  setToken:  (t: string) => void
  clearAuth: () => void
  navigate:  (path: string) => void
}) {
  _getToken  = opts.getToken
  _setToken  = opts.setToken
  _clearAuth = opts.clearAuth
  _navigate  = opts.navigate
}

// ── Request interceptor: attach Bearer token ─────────────────────────────────
apiClient.interceptors.request.use((config) => {
  const token = _getToken?.()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Response interceptor: silent token refresh on 401 ────────────────────────
let isRefreshing = false
let pendingQueue: Array<{ resolve: (token: string) => void; reject: (err: unknown) => void }> = []

function flushQueue(token: string | null, err: unknown = null) {
  pendingQueue.forEach((cb) => (token ? cb.resolve(token) : cb.reject(err)))
  pendingQueue = []
}

apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original: AxiosRequestConfig & { _retry?: boolean } = error.config ?? {}

    // Don't retry refresh calls (loops forever) or login calls (a failed login
    // has no session to refresh — the 401 there means bad credentials, not an
    // expired token, so silently retrying via /auth/refresh only masks the
    // real "Invalid credentials" error with a confusing "No refresh token" one).
    if (
      error.response?.status !== 401 ||
      original._retry ||
      original.url?.includes('/auth/refresh') ||
      original.url?.includes('/auth/login')
    ) {
      return Promise.reject(error)
    }

    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        pendingQueue.push({
          resolve: (token) => {
            if (original.headers) original.headers.Authorization = `Bearer ${token}`
            resolve(apiClient(original))
          },
          reject,
        })
      })
    }

    original._retry = true
    isRefreshing = true

    try {
      const { data } = await apiClient.post<{ access_token: string }>('/auth/refresh')
      _setToken?.(data.access_token)
      if (original.headers) original.headers.Authorization = `Bearer ${data.access_token}`
      flushQueue(data.access_token)
      return apiClient(original)
    } catch (refreshErr) {
      flushQueue(null, refreshErr)
      _clearAuth?.()
      _navigate?.('/login')
      return Promise.reject(refreshErr)
    } finally {
      isRefreshing = false
    }
  }
)
