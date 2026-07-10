import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Role } from '@/utils/constants'

interface AuthState {
  userId:       string | null
  email:        string | null
  displayName:  string | null
  role:         Role | null
  teamId:       string | null
  accessToken:  string | null

  setAuth: (payload: {
    accessToken:  string
    role:         string
    userId:       string
    email:        string
    displayName?: string
    teamId?:      string | null
  }) => void
  setToken:  (token: string) => void
  clearAuth: () => void
  updateProfile: (payload: { display_name?: string; email?: string; role?: string; team_id?: string | null }) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      userId:      null,
      email:       null,
      displayName: null,
      role:        null,
      teamId:      null,
      accessToken: null,

      setAuth: ({ accessToken, role, userId, email, displayName, teamId }) =>
        set({
          accessToken,
          role:        role as Role,
          userId,
          email,
          displayName: displayName ?? null,
          teamId:      teamId ?? null,
        }),

      setToken: (token) => set({ accessToken: token }),

      clearAuth: () =>
        set({ userId: null, email: null, displayName: null, role: null, teamId: null, accessToken: null }),

      updateProfile: ({ display_name, email, role, team_id }) =>
        set((state) => ({
          displayName: display_name ?? state.displayName,
          email:       email ?? state.email,
          role:        (role as Role) ?? state.role,
          teamId:      team_id !== undefined ? team_id : state.teamId,
        })),
    }),
    {
      name: 'aura-auth',
      // Only persist the data fields, not the action functions
      partialize: (state) => ({
        userId:      state.userId,
        email:       state.email,
        displayName: state.displayName,
        role:        state.role,
        teamId:      state.teamId,
        accessToken: state.accessToken,
      }),
    }
  )
)
