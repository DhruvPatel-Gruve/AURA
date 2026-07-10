import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Zap } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { ROLE_NAV } from '@/utils/constants'
import { cn } from '@/utils/cn'
import { AccountSettingsModal } from './AccountSettingsModal'

interface Props {
  collapsed:   boolean
  onToggle:    () => void
}

const ROLE_LABELS: Record<string, string> = {
  master_admin: 'Master Admin',
  admin:      'Administrator',
  manager:    'Manager',
  technician: 'Technician',
  enduser:    'End User',
}

export function Sidebar({ collapsed, onToggle }: Props) {
  const { role, displayName, email } = useAuth()
  const navItems = role ? ROLE_NAV[role] : []
  const [accountOpen, setAccountOpen] = useState(false)

  return (
    <aside
      className={cn(
        'relative flex flex-col h-full',
        'bg-surface',
        'border-r border-line',
        'transition-[width] duration-200 ease-out',
        collapsed ? 'w-14' : 'w-56',
      )}
    >
      {/* Logo strip */}
      <div className={cn(
        'flex items-center gap-2.5 px-3 h-14 border-b border-line shrink-0',
        collapsed && 'justify-center px-0',
      )}>
        <div className="flex items-center justify-center h-7 w-7 rounded-md bg-accent shrink-0">
          <Zap className="h-3.5 w-3.5 text-accent-fg" />
        </div>
        {!collapsed && (
          <span className="font-display font-semibold text-ink tracking-tight">
            AURA
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
        {navItems.map(({ label, path, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            end={path === `/${role}`}
            className={({ isActive }) =>
              cn(
                'nav-item',
                isActive && 'nav-item-active',
                collapsed && 'justify-center px-0 w-10 mx-auto',
              )
            }
            title={collapsed ? label : undefined}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* User chip — click to open Account Settings */}
      {!collapsed && (
        <button
          onClick={() => setAccountOpen(true)}
          className="px-3 py-3 border-t border-line shrink-0 flex items-center gap-2
                     text-left hover:bg-sunken transition-colors"
        >
          <div className="h-7 w-7 rounded-full bg-accent-subtle flex items-center justify-center shrink-0">
            <span className="text-accent text-xs font-semibold uppercase">
              {(displayName ?? email ?? 'U').charAt(0)}
            </span>
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium text-ink truncate">
              {displayName ?? email ?? 'User'}
            </p>
            <p className="text-[11px] text-faint truncate">
              {role ? ROLE_LABELS[role] : ''}
            </p>
          </div>
        </button>
      )}

      <AccountSettingsModal
        open={accountOpen}
        onClose={() => setAccountOpen(false)}
        displayName={displayName}
        email={email}
        role={role}
      />

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        className={cn(
          'absolute -right-3 top-16',
          'h-6 w-6 rounded-full',
          'bg-surface',
          'border border-line',
          'flex items-center justify-center',
          'text-faint hover:text-ink',
          'shadow-sm z-10',
        )}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed
          ? <ChevronRight className="h-3.5 w-3.5" />
          : <ChevronLeft  className="h-3.5 w-3.5" />
        }
      </button>
    </aside>
  )
}
