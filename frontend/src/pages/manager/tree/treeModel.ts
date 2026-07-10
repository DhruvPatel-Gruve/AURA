import type { Edge, Node } from '@xyflow/react'
import type {
  TicketTreeResponse, TreeGroupBy, TreeNodeStats, TreeLeafTicket,
} from '@/api/dashboard.api'

/* ── Shared tree semantics ─────────────────────────────────────────────────
 * Everything that decides how a tree node LOOKS based on what it CONTAINS
 * lives here, so the canvas nodes, the minimap and the legend can't drift. */

export type Health = 'agent' | 'active' | 'warn' | 'critical' | 'neutral'

export function nodeHealth(s: TreeNodeStats): Health {
  if (s.breached > 0) return 'critical'
  if (s.warning > 0) return 'warn'
  if (s.in_review + s.abstained > 0) return 'active'
  if (s.total === 0) return 'neutral'
  return 'agent'
}

export const HEALTH_SPINE: Record<Health, string> = {
  agent:    'spine-agent',
  active:   'spine-active',
  warn:     'spine-warn',
  critical: 'spine-critical',
  neutral:  'spine-neutral',
}

/** Soft gradient tint overlaid on node cards, keyed by health. */
export const HEALTH_TINT: Record<Health, string> = {
  agent:    'from-emerald-500/[0.07]',
  active:   'from-blue-500/[0.06]',
  warn:     'from-amber-500/[0.09]',
  critical: 'from-red-500/[0.09]',
  neutral:  'from-transparent',
}

/** Hex used for minimap + edges, where Tailwind classes can't reach. */
export const HEALTH_HEX: Record<Health, string> = {
  agent:    '#059669',
  active:   '#2563eb',
  warn:     '#d97706',
  critical: '#dc2626',
  neutral:  '#94a3b8',
}

/** Dot/text tone per bucket key. Resolution states and SLA states have fixed
 * meanings; team_category buckets are category names → neutral blue. */
const BUCKET_DOTS: Record<string, string> = {
  resolved_auto:  'bg-emerald-600 dark:bg-emerald-400',
  resolved_human: 'bg-blue-600 dark:bg-blue-400',
  in_review:      'bg-amber-600 dark:bg-amber-400',
  abstained:      'bg-violet-600 dark:bg-violet-400',
  rejected:       'bg-rose-600 dark:bg-rose-400',
  rolled_back:    'bg-rose-600 dark:bg-rose-400',
  halted:         'bg-slate-500 dark:bg-slate-400',
  breached:       'bg-red-600 dark:bg-red-400',
  warning:        'bg-amber-600 dark:bg-amber-400',
  ok:             'bg-emerald-600 dark:bg-emerald-400',
  none:           'bg-slate-400 dark:bg-slate-500',
}

export function bucketDotClass(bucketKey: string): string {
  return BUCKET_DOTS[bucketKey] ?? 'bg-blue-600 dark:bg-blue-400'
}

export const SLA_DOT: Record<TreeLeafTicket['sla_state'], string> = {
  breached: 'bg-red-600 dark:bg-red-400',
  warning:  'bg-amber-600 dark:bg-amber-400',
  ok:       'bg-emerald-600 dark:bg-emerald-400',
  none:     'bg-slate-400 dark:bg-slate-500',
}

export function bucketIdOf(groupKey: string, bucketKey: string): string {
  return `${groupKey}||${bucketKey}`
}

/* ── Node data payloads (cast in/out of React Flow's Node.data) ──────────── */

export interface RootNodeData { stats: TreeNodeStats }
export interface GroupNodeData {
  groupKey: string
  label: string
  stats: TreeNodeStats
  expanded: boolean
  onToggle: (groupKey: string) => void
}
export interface BucketNodeData {
  bucketId: string
  bucketKey: string
  label: string
  stats: TreeNodeStats
  expanded: boolean
  loading: boolean
  onToggle: (bucketId: string) => void
}
export interface LeafNodeData {
  ticket: TreeLeafTicket
  highlighted: boolean
  onOpen: (ticketId: string) => void
}
export interface MoreNodeData {
  bucketId: string
  remaining: number
  canLoadMore: boolean
  onLoadMore: (bucketId: string) => void
}

/* ── Layout ────────────────────────────────────────────────────────────────
 * Simple tidy tree, left → right: each node is vertically centered on its
 * subtree, columns are fixed per depth. No dagre needed for a strict tree. */

export const NODE_SIZE = {
  root:   { w: 300, h: 178 },
  group:  { w: 300, h: 168 },
  bucket: { w: 244, h: 58 },
  leaf:   { w: 296, h: 96 },
  more:   { w: 244, h: 44 },
} as const

const COL_GAP = 88
const GAP_Y = 14
const GROUP_GAP_Y = 30

type NodeKind = keyof typeof NODE_SIZE

interface TN {
  id: string
  kind: NodeKind
  data: unknown
  children: TN[]
  childGap: number
  subtreeH?: number
}

function measure(n: TN): number {
  if (!n.children.length) {
    n.subtreeH = NODE_SIZE[n.kind].h
  } else {
    const kids = n.children.reduce((s, c) => s + measure(c), 0)
      + n.childGap * (n.children.length - 1)
    n.subtreeH = Math.max(NODE_SIZE[n.kind].h, kids)
  }
  return n.subtreeH
}

// x position of each depth column: root, groups, buckets, leaves/more.
const COL_X = [
  0,
  NODE_SIZE.root.w + COL_GAP,
  NODE_SIZE.root.w + NODE_SIZE.group.w + 2 * COL_GAP,
  NODE_SIZE.root.w + NODE_SIZE.group.w + NODE_SIZE.bucket.w + 3 * COL_GAP,
]

function place(n: TN, depth: number, yTop: number, out: Node[], edges: Edge[], edgeStyleFor: (child: TN) => { stroke: string; strokeWidth: number }) {
  const x = COL_X[depth]
  const y = yTop + (n.subtreeH! - NODE_SIZE[n.kind].h) / 2
  out.push({
    id: n.id,
    type: n.kind,
    position: { x, y },
    data: n.data as Record<string, unknown>,
    draggable: false,
    connectable: false,
  })
  let childY = yTop + (n.subtreeH! - (n.children.reduce((s, c) => s + c.subtreeH!, 0) + n.childGap * Math.max(n.children.length - 1, 0))) / 2
  for (const c of n.children) {
    const stats = (c.data as { stats?: TreeNodeStats }).stats
    edges.push({
      id: `e:${n.id}->${c.id}`,
      source: n.id,
      target: c.id,
      type: 'default',   // bezier — organic curves, not stepped corners
      animated: !!stats && (stats.breached > 0 || stats.warning > 0),
      style: edgeStyleFor(c),
    } as Edge)
    place(c, depth + 1, childY, out, edges, edgeStyleFor)
    childY += c.subtreeH! + n.childGap
  }
}

export interface BuildFlowOptions {
  tree: TicketTreeResponse
  groupBy: TreeGroupBy
  expandedGroups: Set<string>
  expandedBuckets: Set<string>
  leaves: Record<string, { items: TreeLeafTicket[]; total: number; loading: boolean } | undefined>
  highlightTicket: string | null
  onToggleGroup: (groupKey: string) => void
  onToggleBucket: (bucketId: string) => void
  onOpenTicket: (ticketId: string) => void
  onLoadMore: (bucketId: string) => void
}

export function buildFlow(opts: BuildFlowOptions): { nodes: Node[]; edges: Edge[] } {
  const {
    tree, expandedGroups, expandedBuckets, leaves, highlightTicket,
    onToggleGroup, onToggleBucket, onOpenTicket, onLoadMore,
  } = opts

  const root: TN = {
    id: 'root',
    kind: 'root',
    data: { stats: tree.root } satisfies RootNodeData,
    childGap: GROUP_GAP_Y,
    children: tree.root.groups.map((g): TN => {
      const gExpanded = expandedGroups.has(g.key)
      return {
        id: `g:${g.key}`,
        kind: 'group',
        data: {
          groupKey: g.key, label: g.label, stats: g, expanded: gExpanded, onToggle: onToggleGroup,
        } satisfies GroupNodeData,
        childGap: GAP_Y,
        children: !gExpanded ? [] : g.buckets.map((b): TN => {
          const bucketId = bucketIdOf(g.key, b.key)
          const bExpanded = expandedBuckets.has(bucketId)
          const leafData = leaves[bucketId]
          const children: TN[] = []
          if (bExpanded && leafData) {
            for (const t of leafData.items) {
              children.push({
                id: `t:${t.ticket_id}`,
                kind: 'leaf',
                data: {
                  ticket: t,
                  highlighted: highlightTicket === t.ticket_id,
                  onOpen: onOpenTicket,
                } satisfies LeafNodeData,
                childGap: 0,
                children: [],
              })
            }
            const remaining = leafData.total - leafData.items.length
            if (remaining > 0) {
              children.push({
                id: `more:${bucketId}`,
                kind: 'more',
                data: {
                  bucketId,
                  remaining,
                  canLoadMore: leafData.items.length < 100,
                  onLoadMore,
                } satisfies MoreNodeData,
                childGap: 0,
                children: [],
              })
            }
          }
          return {
            id: `b:${bucketId}`,
            kind: 'bucket',
            data: {
              bucketId, bucketKey: b.key, label: b.label, stats: b,
              expanded: bExpanded, loading: bExpanded && (leafData?.loading ?? true),
              onToggle: onToggleBucket,
            } satisfies BucketNodeData,
            childGap: GAP_Y,
            children,
          }
        }),
      }
    }),
  }

  measure(root)
  const nodes: Node[] = []
  const edges: Edge[] = []
  place(root, 0, 0, nodes, edges, (child) => {
    const stats = (child.data as { stats?: TreeNodeStats }).stats
    if (!stats) return { stroke: 'rgb(var(--line))', strokeWidth: 1.25 }
    const health = nodeHealth(stats)
    return {
      stroke: health === 'critical' || health === 'warn' ? HEALTH_HEX[health] : 'rgb(var(--line))',
      strokeWidth: Math.min(1.25 + stats.total * 0.12, 5),
    }
  })
  return { nodes, edges }
}
