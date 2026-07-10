import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueries } from '@tanstack/react-query'
import {
  ReactFlow, ReactFlowProvider, Background, BackgroundVariant,
  MiniMap, Controls, useReactFlow, type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Search, Maximize2, Minimize2, Scan,
  ChevronsDownUp, ChevronsUpDown, Info,
} from 'lucide-react'
import { dashboardApi, type TreeGroupBy, type TreeLeafTicket, type TreeNodeStats } from '@/api/dashboard.api'
import { ticketsApi } from '@/api/tickets.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { useToastStore } from '@/store/toastStore'
import { cn } from '@/utils/cn'
import { buildFlow, bucketIdOf, nodeHealth, HEALTH_HEX, NODE_SIZE } from './tree/treeModel'
import { TREE_NODE_TYPES } from './tree/TreeNodes'
import { TicketDetailDrawer } from './tree/TicketDetailDrawer'

const PIVOTS: Array<{ key: TreeGroupBy; label: string; short: string }> = [
  { key: 'category_status', label: 'Category → Status', short: 'Category' },
  { key: 'team_category',   label: 'Team → Category',   short: 'Team' },
  { key: 'priority_sla',    label: 'Priority → SLA',    short: 'Priority' },
]

const LEAF_PAGE = 25

const LEGEND = [
  { cls: 'bg-emerald-600 dark:bg-emerald-400', label: 'Auto-resolved' },
  { cls: 'bg-blue-600 dark:bg-blue-400',       label: 'Human-approved' },
  { cls: 'bg-amber-600 dark:bg-amber-400',     label: 'In review / warning' },
  { cls: 'bg-violet-600 dark:bg-violet-400',   label: 'Abstained' },
  { cls: 'bg-red-600 dark:bg-red-400',         label: 'Breached / error' },
]

export default function TicketTree() {
  return (
    <ReactFlowProvider>
      <TicketTreeInner />
    </ReactFlowProvider>
  )
}

function TicketTreeInner() {
  const [searchParams] = useSearchParams()
  const rf = useReactFlow()
  const showToast = useToastStore((s) => s.show)

  const [groupBy, setGroupBy] = useState<TreeGroupBy>(() => {
    const p = searchParams.get('group_by')
    return PIVOTS.some((x) => x.key === p) ? (p as TreeGroupBy) : 'category_status'
  })
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [expandedGroups, setExpandedGroups]   = useState<Set<string>>(new Set())
  const [expandedBuckets, setExpandedBuckets] = useState<Set<string>>(new Set())
  const [leafLimits, setLeafLimits] = useState<Record<string, number>>({})
  const [selectedTicket, setSelectedTicket] = useState<string | null>(null)
  const [locateId, setLocateId] = useState<string | null>(null)
  const [searchText, setSearchText] = useState('')
  const [fullscreen, setFullscreen] = useState(false)
  const [showLegend, setShowLegend] = useState(true)

  const dateParams = {
    date_from: dateFrom || undefined,
    date_to:   dateTo || undefined,
  }

  const { data: tree, isLoading } = useQuery({
    queryKey: ['manager', 'ticket-tree', groupBy, dateFrom, dateTo],
    queryFn:  () => dashboardApi.getTicketTree({ group_by: groupBy, ...dateParams }),
    refetchInterval: 60_000,
  })

  // Leaf pages — one query per expanded bucket, fetched lazily on expansion.
  const bucketIds = useMemo(() => Array.from(expandedBuckets), [expandedBuckets])
  const leafQueries = useQueries({
    queries: bucketIds.map((bid) => {
      const [group, bucket] = bid.split('||')
      const limit = leafLimits[bid] ?? LEAF_PAGE
      return {
        queryKey: ['manager', 'ticket-tree', 'leaves', groupBy, dateFrom, dateTo, group, bucket, limit],
        queryFn: () => dashboardApi.getTicketTreeTickets({
          group_by: groupBy, group, bucket, page_size: limit, ...dateParams,
        }),
      }
    }),
  })
  const leaves = useMemo(() => {
    const map: Record<string, { items: TreeLeafTicket[]; total: number; loading: boolean } | undefined> = {}
    bucketIds.forEach((bid, i) => {
      const q = leafQueries[i]
      map[bid] = q.data
        ? { items: q.data.items, total: q.data.total, loading: false }
        : { items: [], total: 0, loading: q.isLoading }
    })
    return map
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bucketIds, ...leafQueries.map((q) => q.data), ...leafQueries.map((q) => q.isLoading)])

  // Pivot change invalidates the meaning of every expansion key.
  const changePivot = (p: TreeGroupBy) => {
    if (p === groupBy) return
    setGroupBy(p)
    setExpandedGroups(new Set())
    setExpandedBuckets(new Set())
    setLeafLimits({})
    setLocateId(null)
  }

  const onToggleGroup = useCallback((key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
        // Collapse the group's buckets too, so re-expanding starts clean.
        setExpandedBuckets((pb) => new Set(Array.from(pb).filter((b) => !b.startsWith(`${key}||`))))
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  const onToggleBucket = useCallback((bucketId: string) => {
    setExpandedBuckets((prev) => {
      const next = new Set(prev)
      if (next.has(bucketId)) next.delete(bucketId)
      else next.add(bucketId)
      return next
    })
  }, [])

  const onLoadMore = useCallback((bucketId: string) => {
    setLeafLimits((prev) => ({
      ...prev,
      [bucketId]: Math.min((prev[bucketId] ?? LEAF_PAGE) + LEAF_PAGE, 100),
    }))
  }, [])

  const onOpenTicket = useCallback((id: string) => setSelectedTicket(id), [])

  const { nodes, edges } = useMemo(() => {
    if (!tree) return { nodes: [] as Node[], edges: [] }
    return buildFlow({
      tree, groupBy, expandedGroups, expandedBuckets, leaves,
      highlightTicket: locateId,
      onToggleGroup, onToggleBucket, onOpenTicket, onLoadMore,
    })
  }, [tree, groupBy, expandedGroups, expandedBuckets, leaves, locateId,
      onToggleGroup, onToggleBucket, onOpenTicket, onLoadMore])

  const fitView = useCallback(
    () => rf.fitView({ padding: 0.15, duration: 400 }),
    [rf],
  )

  // Fit once per pivot/date change (not on every expansion — that would
  // fight the user's own pan/zoom).
  const fitKey = `${groupBy}|${dateFrom}|${dateTo}|${tree ? 'ready' : 'loading'}`
  const lastFitRef = useRef('')
  useEffect(() => {
    if (!tree || lastFitRef.current === fitKey) return
    lastFitRef.current = fitKey
    const t = setTimeout(fitView, 60)
    return () => clearTimeout(t)
  }, [fitKey, tree, fitView])

  // ── Fullscreen ──────────────────────────────────────────────────────────
  const toggleFullscreen = useCallback(() => {
    setFullscreen((f) => {
      const next = !f
      // Best-effort native fullscreen for the real edge-to-edge feel; the
      // fixed overlay below is what actually guarantees the layout.
      if (next) document.documentElement.requestFullscreen?.().catch(() => { /* overlay alone is fine */ })
      else if (document.fullscreenElement) document.exitFullscreen?.().catch(() => { /* already out */ })
      // The native fullscreen transition animates the resize — re-fit only
      // after it settles, or React Flow measures a mid-transition viewport.
      setTimeout(fitView, 400)
      return next
    })
  }, [fitView])

  // Any container resize (fullscreen enter/exit, window resize, browser F11)
  // re-fits the view once the dimensions settle.
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>
    const refit = () => {
      clearTimeout(t)
      t = setTimeout(fitView, 250)
    }
    window.addEventListener('resize', refit)
    document.addEventListener('fullscreenchange', refit)
    return () => {
      clearTimeout(t)
      window.removeEventListener('resize', refit)
      document.removeEventListener('fullscreenchange', refit)
    }
  }, [fitView])

  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // Drawer first, canvas second — matches how layered UIs dismiss.
      if (selectedTicket) setSelectedTicket(null)
      else toggleFullscreen()
    }
    // Browser Esc exits native fullscreen without a keydown we can catch —
    // sync our overlay state off the fullscreenchange event instead.
    const onFsChange = () => {
      if (!document.fullscreenElement) {
        setFullscreen(false)
        setTimeout(fitView, 120)
      }
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('fullscreenchange', onFsChange)
    }
  }, [fullscreen, toggleFullscreen, fitView, selectedTicket])

  // Drill-through support: /manager/tree?group_by=...&expand=GroupKey
  const drilledRef = useRef(false)
  useEffect(() => {
    if (drilledRef.current || !tree) return
    drilledRef.current = true
    const expand = searchParams.get('expand')
    if (expand && tree.root.groups.some((g) => g.key === expand)) {
      setExpandedGroups(new Set([expand]))
    }
  }, [tree, searchParams])

  // Search → locate: find the ticket via the ticket list, expand its group
  // and all buckets in it, then center once its leaf node exists.
  const handleSearch = async () => {
    const q = searchText.trim()
    if (!q || !tree) return
    try {
      const res = await ticketsApi.list({ ticket_id: q, page_size: 5 })
      const hit = res.items.find((t) => t.ticket_id.toLowerCase() === q.toLowerCase()) ?? res.items[0]
      if (!hit) {
        showToast(`No processed ticket matching "${q}"`, 'warning')
        return
      }
      const groupKey = groupBy === 'category_status' ? (hit.category ?? 'Uncategorized')
        : groupBy === 'team_category' ? (hit.team_id ?? 'Unassigned')
        : (hit.priority ?? 'None')
      const group = tree.root.groups.find((g) => g.key === groupKey)
      if (!group) {
        showToast(`Ticket ${hit.ticket_id} is outside the current filters`, 'warning')
        return
      }
      setExpandedGroups((prev) => new Set(prev).add(group.key))
      setExpandedBuckets((prev) => {
        const next = new Set(prev)
        group.buckets.forEach((b) => next.add(bucketIdOf(group.key, b.key)))
        return next
      })
      setLocateId(hit.ticket_id)
    } catch {
      showToast('Search failed — is the backend reachable?', 'warning')
    }
  }

  // Center on the located leaf as soon as it materialises, then let the
  // highlight fade after a moment.
  useEffect(() => {
    if (!locateId) return
    const node = nodes.find((n) => n.id === `t:${locateId}`)
    if (!node) return
    rf.setCenter(
      node.position.x + NODE_SIZE.leaf.w / 2,
      node.position.y + NODE_SIZE.leaf.h / 2,
      { zoom: 1.1, duration: 500 },
    )
    const t = setTimeout(() => setLocateId(null), 4000)
    return () => clearTimeout(t)
  }, [locateId, nodes, rf])

  const expandAll = () => {
    if (!tree) return
    setExpandedGroups(new Set(tree.root.groups.map((g) => g.key)))
    setExpandedBuckets(new Set(
      tree.root.groups.flatMap((g) => g.buckets.map((b) => bucketIdOf(g.key, b.key))),
    ))
  }
  const collapseAll = () => {
    setExpandedGroups(new Set())
    setExpandedBuckets(new Set())
  }

  const canvas = (
    <div
      className={cn(
        'ticket-tree-canvas relative overflow-hidden',
        fullscreen
          ? 'fixed inset-0 z-[60] bg-canvas'
          : 'card flex-1 min-h-[540px]',
      )}
    >
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface/60 z-10">
          <LoadingSpinner size="lg" />
        </div>
      )}

      {tree && tree.root.total === 0 && !isLoading ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center px-6">
          <p className="text-sm font-medium text-ink">No tickets in this window</p>
          <p className="text-xs text-faint max-w-sm">
            AURA builds this map as tickets flow through the pipeline. Widen the
            date range, or submit a test ticket and let the poller pick it up.
          </p>
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={TREE_NODE_TYPES}
          fitView
          minZoom={0.15}
          maxZoom={1.75}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          deleteKeyCode={null}
        >
          <Background variant={BackgroundVariant.Dots} gap={26} size={1.25} color="rgb(var(--line))" />
          <MiniMap
            pannable
            zoomable
            className="!bg-sunken/80 !backdrop-blur !border !border-line !rounded-xl overflow-hidden"
            maskColor="rgb(var(--canvas) / 0.75)"
            nodeColor={(n) => {
              const stats = (n.data as { stats?: TreeNodeStats }).stats
              return stats ? HEALTH_HEX[nodeHealth(stats)] : 'rgb(var(--faint))'
            }}
          />
          <Controls showInteractive={false} className="!bg-surface !border !border-line !rounded-xl !shadow-card overflow-hidden" />
        </ReactFlow>
      )}

      {/* Floating toolbar — lives inside the canvas so it survives fullscreen */}
      <div className="absolute top-3 left-3 z-20 glass flex items-center flex-wrap gap-1.5 p-1.5 max-w-[calc(100%-180px)]">
        <div className="inline-flex rounded-lg bg-sunken/70 p-0.5">
          {PIVOTS.map((p) => (
            <button
              key={p.key}
              onClick={() => changePivot(p.key)}
              title={p.label}
              className={cn(
                'px-2.5 h-7 rounded-md text-xs font-medium transition-colors',
                groupBy === p.key ? 'bg-surface text-accent shadow-sm' : 'text-body hover:text-ink',
              )}
            >
              {p.short}
            </button>
          ))}
        </div>
        <div className="w-px h-5 bg-line/70 mx-0.5" />
        <input
          type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
          className="input-base !w-[8.5rem] !h-7 !py-0 !px-2 !text-xs !bg-transparent !border-0 hover:!bg-sunken/70 !rounded-md"
        />
        <span className="text-[10px] text-faint">→</span>
        <input
          type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
          className="input-base !w-[8.5rem] !h-7 !py-0 !px-2 !text-xs !bg-transparent !border-0 hover:!bg-sunken/70 !rounded-md"
        />
        <div className="w-px h-5 bg-line/70 mx-0.5" />
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-faint" />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Locate ticket…"
            className="input-base !w-36 !h-7 !py-0 !pl-6 !pr-2 !text-xs !bg-transparent !border-0 hover:!bg-sunken/70 focus:!bg-surface !rounded-md"
          />
        </div>
        <div className="w-px h-5 bg-line/70 mx-0.5" />
        <ToolButton title="Expand all" onClick={expandAll}><ChevronsUpDown className="h-3.5 w-3.5" /></ToolButton>
        <ToolButton title="Collapse all" onClick={collapseAll}><ChevronsDownUp className="h-3.5 w-3.5" /></ToolButton>
        <ToolButton title="Fit view" onClick={fitView}><Scan className="h-3.5 w-3.5" /></ToolButton>
        <ToolButton title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'} onClick={toggleFullscreen} active={fullscreen}>
          {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </ToolButton>
      </div>

      {/* Legend — collapsible glass chip, top-right */}
      <div className="absolute top-3 right-3 z-20 flex flex-col items-end gap-1.5">
        <button
          onClick={() => setShowLegend((s) => !s)}
          className="glass h-8 w-8 flex items-center justify-center text-body hover:text-ink transition-colors"
          title={showLegend ? 'Hide legend' : 'Show legend'}
        >
          <Info className="h-3.5 w-3.5" />
        </button>
        {showLegend && (
          <div className="glass px-3 py-2 flex flex-col gap-1.5">
            {LEGEND.map((l) => (
              <div key={l.label} className="flex items-center gap-2">
                <span className={cn('h-2 w-2 rounded-full shrink-0', l.cls)} />
                <span className="text-[11px] text-body whitespace-nowrap">{l.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full space-y-4">
      {!fullscreen && (
        <PageHeader
          title="Ticket Tree"
          description="Live map of every ticket AURA has processed — expand a branch to drill from totals to individual tickets"
          className="!mb-0"
        />
      )}

      {canvas}

      <TicketDetailDrawer ticketId={selectedTicket} onClose={() => setSelectedTicket(null)} />
    </div>
  )
}

function ToolButton({ title, onClick, active, children }: {
  title: string
  onClick: () => void
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        'h-7 w-7 flex items-center justify-center rounded-md transition-colors',
        active ? 'bg-accent-subtle text-accent' : 'text-body hover:bg-sunken/70 hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}
