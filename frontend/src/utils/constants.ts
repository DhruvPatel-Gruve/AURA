import {
  LayoutDashboard, Users, Tag, Settings, Power,
  RotateCcw, FileText, Database, Activity,
  BarChart2, TrendingUp, Target, UserCheck,
  AlertCircle, CheckSquare,
  Inbox, MessageSquare, PlusCircle, Users2,
  Network, Building2, Plug,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export const ROLES = ['master_admin', 'admin', 'manager', 'technician', 'enduser'] as const
export type Role = (typeof ROLES)[number]

// The active ITSM provider — set once at setup and displayed throughout the
// app so labels/copy stay accurate regardless of which backend AURA talks to.
export type ItsmProvider = 'jira' | 'zendesk'
export const ITSM_PROVIDER_LABELS: Record<ItsmProvider, string> = {
  jira:    'Jira Service Management',
  zendesk: 'Zendesk',
}
export const ITSM_PROVIDER_SHORT_LABELS: Record<ItsmProvider, string> = {
  jira:    'Jira',
  zendesk: 'Zendesk',
}

export const ROLE_HOME: Record<Role, string> = {
  master_admin: '/master',
  admin:      '/admin',
  manager:    '/manager',
  technician: '/technician',
  enduser:    '/enduser',
}

export interface NavItem {
  label: string
  path:  string
  icon:  LucideIcon
}

export const ROLE_NAV: Record<Role, NavItem[]> = {
  master_admin: [
    { label: 'Tenants',       path: '/master',              icon: Building2       },
  ],
  admin: [
    { label: 'Dashboard',      path: '/admin',             icon: LayoutDashboard },
    { label: 'Users',          path: '/admin/users',        icon: Users           },
    { label: 'Categories',     path: '/admin/categories',   icon: Tag             },
    { label: 'Agent Config',   path: '/admin/config',       icon: Settings        },
    { label: 'Integrations',   path: '/admin/integrations', icon: Plug            },
    { label: 'Kill Switch',    path: '/admin/kill-switch',  icon: Power           },
    { label: 'Rollback',       path: '/admin/rollback',     icon: RotateCcw       },
    { label: 'Audit Log',      path: '/admin/audit-log',    icon: FileText        },
    { label: 'Knowledge Index',path: '/admin/qdrant',       icon: Database        },
    { label: 'System Health',  path: '/admin/health',       icon: Activity        },
  ],
  manager: [
    { label: 'Dashboard',      path: '/manager',             icon: LayoutDashboard },
    { label: 'Ticket Tree',    path: '/manager/tree',        icon: Network         },
    { label: 'SLA Compliance', path: '/manager/sla',         icon: Target          },
    { label: 'Resolution',     path: '/manager/resolution',  icon: TrendingUp      },
    { label: 'Confidence',     path: '/manager/confidence',  icon: BarChart2       },
    { label: 'Team',           path: '/manager/team',        icon: UserCheck       },
    { label: 'Abstention',     path: '/manager/abstention',  icon: AlertCircle     },
    { label: 'Collisions',     path: '/manager/collisions',  icon: Users2          },
    { label: 'Approvals',      path: '/manager/approvals',   icon: CheckSquare     },
  ],
  technician: [
    { label: 'Dashboard',       path: '/technician',                  icon: LayoutDashboard },
    { label: 'Tickets',         path: '/technician/queue',            icon: Inbox           },
  ],
  enduser: [
    { label: 'Dashboard',    path: '/enduser',         icon: LayoutDashboard },
    { label: 'My Tickets',   path: '/enduser/tickets', icon: Inbox           },
    { label: 'Submit Ticket',path: '/enduser/submit',  icon: PlusCircle      },
    { label: 'Live Chat',    path: '/enduser/chat',    icon: MessageSquare   },
  ],
}

export const WS_EVENTS = {
  CONNECTED:              'CONNECTED',
  TICKET_ASSIGNED:        'TICKET_ASSIGNED',
  TICKET_UPDATED:         'TICKET_UPDATED',
  TICKET_REASSIGNED:      'TICKET_REASSIGNED',
  ASSIGNMENT_OVERDUE:     'ASSIGNMENT_OVERDUE',
  AURA_COMMENT_POSTED:    'AURA_COMMENT_POSTED',
  LOW_CONFIDENCE_QUEUED:  'LOW_CONFIDENCE_QUEUED',
  ABSTENTION_FLAGGED:     'ABSTENTION_FLAGGED',
  SLA_WARNING:            'SLA_WARNING',
  SLA_BREACHED:           'SLA_BREACHED',
  KILL_SWITCH_ACTIVATED:  'KILL_SWITCH_ACTIVATED',
  KILL_SWITCH_DEACTIVATED:'KILL_SWITCH_DEACTIVATED',
  INGESTION_PROGRESS:     'INGESTION_PROGRESS',
  INGESTION_COMPLETE:     'INGESTION_COMPLETE',
  TICKET_CLAIMED:         'TICKET_CLAIMED',
  TICKET_UNCLAIMED:       'TICKET_UNCLAIMED',
  USER_UPDATED:           'USER_UPDATED',
} as const
