import { create } from 'zustand'
import { hexToRgbString, lightenHex } from '@/utils/formatters'
import type { ItsmProvider } from '@/utils/constants'

export type Theme = 'light' | 'dark'

interface ConfigState {
  killSwitchActive: boolean
  accentColor:      string
  companyName:      string
  companyLogo:      string   // base64 data URL, empty string if not set
  theme:            Theme
  setupComplete:    boolean | null
  itsmProvider:     ItsmProvider

  setKillSwitch:       (active: boolean) => void
  setAccentColor:      (hex: string) => void
  setCompanyBranding:  (name: string, logo: string, accent: string) => void
  clearBranding:       () => void
  setTheme:            (theme: Theme) => void
  initTheme:           () => void
  setSetupComplete:    (v: boolean) => void
  setItsmProvider:     (provider: ItsmProvider) => void
}

function applyAccent(hex: string) {
  const rgb   = hexToRgbString(hex)
  const hover = hexToRgbString(lightenHex(hex, 0.18))
  if (rgb)   document.documentElement.style.setProperty('--accent', rgb)
  if (hover) document.documentElement.style.setProperty('--accent-hover', hover)
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export const DEFAULT_ACCENT = '#3db549'

export const useConfigStore = create<ConfigState>((set) => ({
  killSwitchActive: false,
  accentColor:      DEFAULT_ACCENT,
  companyName:      '',
  companyLogo:      '',
  theme:            'light',
  setupComplete:    null,
  itsmProvider:     'jira',

  setKillSwitch:    (active) => set({ killSwitchActive: active }),
  setSetupComplete: (v)      => set({ setupComplete: v }),
  setItsmProvider:  (provider) => set({ itsmProvider: provider }),

  setAccentColor: (hex) => {
    applyAccent(hex)
    localStorage.setItem('accentColor', hex)
    set({ accentColor: hex })
  },

  setCompanyBranding: (name, logo, accent) => {
    if (accent) applyAccent(accent)
    localStorage.setItem('companyName', name)
    localStorage.setItem('companyLogo', logo)
    if (accent) localStorage.setItem('accentColor', accent)
    set({
      companyName: name,
      companyLogo: logo,
      ...(accent ? { accentColor: accent } : {}),
    })
  },

  // Forces the generic AURA identity — no tenant logo/name/accent. Used for
  // master_admin, which has no tenant_id and should never show client branding.
  clearBranding: () => {
    applyAccent(DEFAULT_ACCENT)
    localStorage.setItem('companyName', '')
    localStorage.setItem('companyLogo', '')
    localStorage.setItem('accentColor', DEFAULT_ACCENT)
    set({ companyName: '', companyLogo: '', accentColor: DEFAULT_ACCENT })
  },

  setTheme: (theme) => {
    applyTheme(theme)
    localStorage.setItem('theme', theme)
    set({ theme })
  },

  // Restore persisted preferences on app mount
  initTheme: () => {
    const savedTheme  = (localStorage.getItem('theme') as Theme | null) ?? 'light'
    const raw         = localStorage.getItem('accentColor')
    // Migrate from old indigo default
    const savedAccent = (!raw || raw === '#6366f1') ? DEFAULT_ACCENT : raw
    const savedName   = localStorage.getItem('companyName') ?? ''
    const savedLogo   = localStorage.getItem('companyLogo') ?? ''

    applyTheme(savedTheme)
    applyAccent(savedAccent)
    set({
      theme:       savedTheme,
      accentColor: savedAccent,
      companyName: savedName,
      companyLogo: savedLogo,
    })
  },
}))
