import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { motion } from 'framer-motion'
import { ChevronRight, User, Plus, Loader2 } from 'lucide-react'
import { cn } from '@/utils/cn'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import type { TreeNodeStats } from '@/api/dashboard.api'
import {
  nodeHealth, HEALTH_SPINE, HEALTH_TINT, bucketDotClass, SLA_DOT,
  type RootNodeData, type GroupNodeData, type BucketNodeData,
  type LeafNodeData, type MoreNodeData,
} from './treeModel'

/* ── Shared fragments ─────────────────────────────────────────────────────── */

const appear = {
  initial: { opacity: 0, scale: 0.94 },
  animate: { opacity: 1, scale: 1 },
  transition: { duration: 0.2, ease: 'easeOut' as const },
}

const lift = { y: -2, transition: { duration: 0.15 } }

function Ports({ left, right }: { left?: boolean; right?: boolean }) {
  return (
    <>
      {left && <Handle type="target" position={Position.Left} className="!w-1 !h-1 !min-w-0 !min-h-0 !border-0 !bg-transparent" />}
      {right && <Handle type="source" position={Position.Right} className="!w-1 !h-1 !min-w-0 !min-h-0 !border-0 !bg-transparent" />}
    </>
  )
}

/** Soft health-tinted wash over the card, fading to transparent. */
function Tint({ stats }: { stats: TreeNodeStats }) {
  return (
    <div className={cn(
      'absolute inset-0 pointer-events-none rounded-2xl bg-gradient-to-br via-transparent to-transparent',
      HEALTH_TINT[nodeHealth(stats)],
    )} />
  )
}

/** SLA compliance micro-ring. Green ≥90, amber ≥70, red below. */
function MiniRing({ pct, size = 44 }: { pct: number | null; size?: number }) {
  const r = (size - 6) / 2
  const c = 2 * Math.PI * r
  const color = pct == null ? 'rgb(var(--faint))'
    : pct >= 90 ? '#059669' : pct >= 70 ? '#d97706' : '#dc2626'
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--line))" strokeWidth={3.5} />
        {pct != null && (
          <circle
            cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke={color} strokeWidth={3.5} strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)}
            style={{ transition: 'stroke-dashoffset 400ms ease-out' }}
          />
        )}
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[10px] text-body">
        {pct != null ? `${Math.round(pct)}%` : '—'}
      </span>
    </div>
  )
}

/** Stacked outcome-split bar: auto / human / review / abstained / other. */
function SplitBar({ stats }: { stats: TreeNodeStats }) {
  const other = stats.total - stats.auto_resolved - stats.human_resolved - stats.in_review - stats.abstained
  const segs = [
    { n: stats.auto_resolved,  cls: 'bg-emerald-600 dark:bg-emerald-400', label: 'Auto' },
    { n: stats.human_resolved, cls: 'bg-blue-600 dark:bg-blue-400',       label: 'Human' },
    { n: stats.in_review,      cls: 'bg-amber-600 dark:bg-amber-400',     label: 'Review' },
    { n: stats.abstained,      cls: 'bg-violet-600 dark:bg-violet-400',   label: 'Abstained' },
    { n: Math.max(other, 0),   cls: 'bg-slate-400 dark:bg-slate-500',     label: 'Other' },
  ].filter((s) => s.n > 0)
  if (!stats.total) return <div className="h-1.5 rounded-full bg-sunken" />
  return (
    <div className="flex h-1.5 rounded-full overflow-hidden bg-sunken gap-px" title={segs.map((s) => `${s.label} ${s.n}`).join(' · ')}>
      {segs.map((s) => (
        <div key={s.label} className={cn('rounded-full', s.cls)} style={{ width: `${(s.n / stats.total) * 100}%` }} />
      ))}
    </div>
  )
}

function ConfidenceInline({ value }: { value: number | null }) {
  if (value == null) return <span className="font-mono text-[11px] text-faint">conf —</span>
  const tone = value >= 0.9 ? 'text-emerald-600 dark:text-emerald-400'
    : value >= 0.6 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'
  return <span className={cn('font-mono text-[11px]', tone)}>conf {(value * 100).toFixed(0)}%</span>
}

const PRIORITY_TONE: Record<string, BadgeTone> = {
  Highest: 'critical', Critical: 'critical', High: 'critical',
  Medium: 'warn', Low: 'neutral', Lowest: 'neutral',
}

/* ── Node components ──────────────────────────────────────────────────────── */

export const RootNode = memo(function RootNode(props: NodeProps) {
  const { stats } = props.data as unknown as RootNodeData
  return (
    <motion.div
      {...appear}
      className={cn(
        'relative w-[300px] rounded-2xl border border-line bg-surface shadow-card p-4 overflow-hidden',
        HEALTH_SPINE[nodeHealth(stats)],
      )}
    >
      <div className="absolute inset-0 pointer-events-none rounded-2xl bg-gradient-to-br from-accent/[0.08] via-transparent to-transparent" />
      <Ports right />
      <div className="relative flex items-start justify-between gap-3">
        <div>
          <p className="overline-label">All Tickets</p>
          <p className="font-mono text-3xl font-semibold text-ink leading-9">{stats.total}</p>
        </div>
        <MiniRing pct={stats.sla_compliance_pct} size={52} />
      </div>
      <div className="relative mt-3 space-y-2">
        <SplitBar stats={stats} />
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge tone="success" mono>{stats.auto_resolved} auto</Badge>
          <Badge tone="info" mono>{stats.human_resolved} human</Badge>
          {stats.in_review > 0 && <Badge tone="warn" mono>{stats.in_review} review</Badge>}
          {stats.breached > 0 && <Badge tone="critical" dot mono>{stats.breached} breached</Badge>}
        </div>
        <p className="text-[11px] text-faint">
          SLA compliance{stats.avg_confidence != null && <> · avg confidence <span className="font-mono">{(stats.avg_confidence * 100).toFixed(0)}%</span></>}
        </p>
      </div>
    </motion.div>
  )
})

export const GroupNode = memo(function GroupNode(props: NodeProps) {
  const { groupKey, label, stats, expanded, onToggle } = props.data as unknown as GroupNodeData
  return (
    <motion.div
      {...appear}
      whileHover={lift}
      onClick={() => onToggle(groupKey)}
      className={cn(
        'relative w-[300px] rounded-2xl border border-line bg-surface shadow-card p-4 overflow-hidden',
        'cursor-pointer select-none hover:shadow-card-md transition-shadow',
        expanded && 'ring-1 ring-line',
        HEALTH_SPINE[nodeHealth(stats)],
      )}
    >
      <Tint stats={stats} />
      <Ports left right={expanded} />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1">
            <ChevronRight className={cn('h-3.5 w-3.5 text-faint transition-transform shrink-0', expanded && 'rotate-90')} />
            <p className="overline-label truncate" title={label}>{label}</p>
          </div>
          <p className="font-mono text-2xl font-semibold text-ink leading-8 ml-[18px]">{stats.total}</p>
        </div>
        <MiniRing pct={stats.sla_compliance_pct} />
      </div>
      <div className="relative mt-3 space-y-2">
        <SplitBar stats={stats} />
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            {stats.breached > 0 && <Badge tone="critical" dot mono>{stats.breached} breached</Badge>}
            {stats.warning > 0 && <Badge tone="warn" mono>{stats.warning} at risk</Badge>}
            {stats.in_review > 0 && <Badge tone="warn" mono>{stats.in_review} review</Badge>}
          </div>
          <ConfidenceInline value={stats.avg_confidence} />
        </div>
      </div>
    </motion.div>
  )
})

export const BucketNode = memo(function BucketNode(props: NodeProps) {
  const { bucketId, bucketKey, label, stats, expanded, loading, onToggle } = props.data as unknown as BucketNodeData
  return (
    <motion.div
      {...appear}
      whileHover={{ x: 3, transition: { duration: 0.15 } }}
      onClick={() => onToggle(bucketId)}
      className={cn(
        'w-[244px] h-[58px] rounded-full border border-line bg-surface shadow-card px-4',
        'flex items-center gap-2.5 cursor-pointer select-none hover:shadow-card-md transition-shadow',
        expanded && 'ring-1 ring-line',
      )}
    >
      <Ports left right={expanded} />
      <span className={cn('h-2.5 w-2.5 rounded-full shrink-0 ring-4 ring-sunken', bucketDotClass(bucketKey))} />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-ink truncate">{label}</p>
        <p className="text-[11px] text-faint">
          {stats.breached > 0 ? <span className="text-red-600 dark:text-red-400">{stats.breached} breached</span> : 'tickets'}
        </p>
      </div>
      <span className="font-mono text-lg font-semibold text-ink">{stats.total}</span>
      {loading
        ? <Loader2 className="h-3.5 w-3.5 text-faint animate-spin shrink-0" />
        : <ChevronRight className={cn('h-3.5 w-3.5 text-faint transition-transform shrink-0', expanded && 'rotate-90')} />}
    </motion.div>
  )
})

export const LeafNode = memo(function LeafNode(props: NodeProps) {
  const { ticket: t, highlighted, onOpen } = props.data as unknown as LeafNodeData
  return (
    <motion.div
      {...appear}
      whileHover={lift}
      onClick={() => onOpen(t.ticket_id)}
      className={cn(
        'w-[296px] rounded-xl border border-line bg-surface shadow-card p-3',
        'cursor-pointer select-none hover:shadow-card-md transition-shadow',
        HEALTH_SPINE[t.sla_state === 'breached' ? 'critical' : t.sla_state === 'warning' ? 'warn' : 'neutral'],
        highlighted && 'ring-2 ring-accent animate-pulse',
      )}
    >
      <Ports left />
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-semibold text-ink truncate">{t.ticket_id}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          {t.priority !== 'None' && (
            <Badge tone={PRIORITY_TONE[t.priority] ?? 'neutral'}>{t.priority}</Badge>
          )}
          <span className={cn('h-1.5 w-1.5 rounded-full', SLA_DOT[t.sla_state])} title={`SLA: ${t.sla_state}`} />
        </div>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px]">
        <span className="text-body truncate">{t.workflow_status ?? '—'}</span>
        <ConfidenceInline value={t.confidence_score} />
      </div>
      <div className="mt-1 flex items-center gap-1 text-[11px] text-faint min-w-0">
        <User className="h-3 w-3 shrink-0" />
        <span className="truncate">{t.assignee_name ?? 'Unassigned'}</span>
        {t.assignee_name && !t.acknowledged && <span className="text-amber-600 dark:text-amber-400 shrink-0">· unacked</span>}
      </div>
    </motion.div>
  )
})

export const MoreNode = memo(function MoreNode(props: NodeProps) {
  const { bucketId, remaining, canLoadMore, onLoadMore } = props.data as unknown as MoreNodeData
  return (
    <motion.div
      {...appear}
      onClick={() => canLoadMore && onLoadMore(bucketId)}
      className={cn(
        'w-[244px] h-[44px] rounded-full border border-dashed border-line bg-transparent',
        'flex items-center justify-center gap-1.5 text-xs text-body select-none',
        canLoadMore ? 'cursor-pointer hover:bg-sunken hover:text-ink transition-colors' : 'cursor-default text-faint',
      )}
    >
      <Ports left />
      <Plus className="h-3.5 w-3.5" />
      {canLoadMore ? `Load ${Math.min(remaining, 25)} more` : `${remaining} more — narrow the date range`}
    </motion.div>
  )
})

export const TREE_NODE_TYPES = {
  root: RootNode,
  group: GroupNode,
  bucket: BucketNode,
  leaf: LeafNode,
  more: MoreNode,
}
