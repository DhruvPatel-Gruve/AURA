import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Check, X } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { AutonomyBadge } from '@/components/ui/AutonomyBadge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { cn } from '@/utils/cn'
import type { CategoryConfig } from '@/api/types'

interface EditState {
  name:                 string
  sla_minutes:          number
  auto_comment_enabled: boolean
  team_id:              string
}

const DEFAULT_SLA = 240

function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0',
        checked ? 'bg-accent' : 'bg-sunken ring-1 ring-inset ring-line',
      )}
    >
      <span
        className={cn(
          'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
          checked ? 'translate-x-[18px]' : 'translate-x-0.5',
        )}
      />
    </button>
  )
}

export default function CategoryManagement() {
  const qc = useQueryClient()
  const [editId, setEditId]   = useState<string | null>(null)
  const [editState, setEdit]  = useState<EditState>({ name: '', sla_minutes: DEFAULT_SLA, auto_comment_enabled: false, team_id: '' })
  const [adding, setAdding]   = useState(false)
  const [newRow, setNewRow]   = useState<EditState>({ name: '', sla_minutes: DEFAULT_SLA, auto_comment_enabled: false, team_id: '' })

  const [teamFilter, setTeamFilter] = useState('')

  const { data: cats, isLoading } = useQuery({
    queryKey: ['admin', 'categories'],
    queryFn:  adminApi.getCategories,
  })

  const teamOptions = Array.from(new Set((cats ?? []).map((c) => c.team_id).filter(Boolean))).sort()
  const visibleCats = (cats ?? []).filter((c) => !teamFilter || c.team_id === teamFilter)

  const createMutation = useMutation({
    mutationFn: (d: EditState) => adminApi.createCategory(d),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'categories'] }); setAdding(false); setNewRow({ name: '', sla_minutes: DEFAULT_SLA, auto_comment_enabled: false, team_id: '' }) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<EditState> }) => adminApi.updateCategory(id, data),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'categories'] }); setEditId(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => adminApi.deleteCategory(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['admin', 'categories'] }),
  })

  const startEdit = (cat: CategoryConfig) => {
    setEditId(cat.category_id)
    setEdit({ name: cat.name, sla_minutes: cat.sla_minutes, auto_comment_enabled: cat.auto_comment_enabled, team_id: cat.team_id })
  }

  const cancelEdit = () => setEditId(null)

  const saveEdit = (id: string) => updateMutation.mutate({ id, data: editState })

  const slaLabel = (mins: number) => {
    if (mins < 60) return `${mins}m`
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Category Management"
        description="Configure ticket categories, SLA targets, and auto-comment behavior"
        actions={
          <button onClick={() => setAdding(true)} className="btn-primary" disabled={adding}>
            <Plus className="h-4 w-4" />
            Add Category
          </button>
        }
      />

      {teamOptions.length > 0 && (
        <div className="flex items-center gap-2">
          <select value={teamFilter} onChange={(e) => setTeamFilter(e.target.value)} className="input-base w-48 text-sm">
            <option value="">All teams</option>
            {teamOptions.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      )}

      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <LoadingSpinner />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {['Category', 'SLA Target', 'Team', 'Auto Comment', 'Actions'].map((h) => (
                    <th key={h} className="table-head">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Add new row */}
                {adding && (
                  <tr className="bg-accent-subtle/40">
                    <td className="table-cell !py-2">
                      <input
                        autoFocus
                        className="input-base !py-1"
                        placeholder="Category name"
                        value={newRow.name}
                        onChange={(e) => setNewRow((r) => ({ ...r, name: e.target.value }))}
                      />
                    </td>
                    <td className="table-cell !py-2">
                      <input
                        type="number"
                        min={1}
                        className="input-base !py-1 w-24 font-mono tabular-nums"
                        value={newRow.sla_minutes}
                        onChange={(e) => setNewRow((r) => ({ ...r, sla_minutes: Number(e.target.value) }))}
                      />
                      <span className="ml-1 text-xs text-faint">min</span>
                    </td>
                    <td className="table-cell !py-2">
                      <input
                        className="input-base !py-1 w-28 font-mono"
                        placeholder="team-id"
                        value={newRow.team_id}
                        onChange={(e) => setNewRow((r) => ({ ...r, team_id: e.target.value }))}
                      />
                    </td>
                    <td className="table-cell !py-2">
                      <ToggleSwitch
                        checked={newRow.auto_comment_enabled}
                        onChange={(v) => setNewRow((r) => ({ ...r, auto_comment_enabled: v }))}
                      />
                    </td>
                    <td className="table-cell !py-2">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => createMutation.mutate(newRow)}
                          disabled={!newRow.name || createMutation.isPending}
                          className="btn-primary !px-2 !py-1 text-xs"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => setAdding(false)} className="btn-ghost !px-2 !py-1">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )}

                {visibleCats.map((cat) => {
                  const isEditing = editId === cat.category_id
                  return (
                    <tr
                      key={cat.category_id}
                      className="hover:bg-sunken transition-colors"
                      onDoubleClick={() => !isEditing && startEdit(cat)}
                    >
                      <td className="table-cell font-medium">
                        {isEditing ? (
                          <input
                            autoFocus
                            className="input-base !py-1"
                            value={editState.name}
                            onChange={(e) => setEdit((s) => ({ ...s, name: e.target.value }))}
                          />
                        ) : cat.name}
                      </td>
                      <td className="table-cell !text-body">
                        {isEditing ? (
                          <div className="flex items-center gap-1">
                            <input
                              type="number"
                              min={1}
                              className="input-base !py-1 w-20 font-mono tabular-nums"
                              value={editState.sla_minutes}
                              onChange={(e) => setEdit((s) => ({ ...s, sla_minutes: Number(e.target.value) }))}
                            />
                            <span className="text-xs text-faint">min</span>
                          </div>
                        ) : <span className="font-mono tabular-nums">{slaLabel(cat.sla_minutes)}</span>}
                      </td>
                      <td className="table-cell !text-body">
                        {isEditing ? (
                          <input
                            className="input-base !py-1 w-28 font-mono"
                            placeholder="team-id"
                            value={editState.team_id}
                            onChange={(e) => setEdit((s) => ({ ...s, team_id: e.target.value }))}
                          />
                        ) : (cat.team_id
                          ? <span className="font-mono">{cat.team_id}</span>
                          : <span className="text-xs text-faint">—</span>)}
                      </td>
                      <td className="table-cell">
                        {isEditing ? (
                          <ToggleSwitch
                            checked={editState.auto_comment_enabled}
                            onChange={(v) => setEdit((s) => ({ ...s, auto_comment_enabled: v }))}
                          />
                        ) : (
                          <div className="flex items-center gap-2">
                            <ToggleSwitch
                              checked={cat.auto_comment_enabled}
                              onChange={(v) => updateMutation.mutate({ id: cat.category_id, data: { auto_comment_enabled: v } })}
                            />
                            <AutonomyBadge enabled={cat.auto_comment_enabled} />
                          </div>
                        )}
                      </td>
                      <td className="table-cell">
                        {isEditing ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => saveEdit(cat.category_id)}
                              disabled={updateMutation.isPending}
                              className="btn-primary !px-2 !py-1 text-xs"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={cancelEdit} className="btn-ghost !px-2 !py-1">
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => startEdit(cat)}
                              className="btn-ghost !px-2 !py-1 text-xs"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => deleteMutation.mutate(cat.category_id)}
                              className="btn-ghost !px-2 !py-1 text-red-600 hover:text-red-700 dark:text-red-400"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
                {visibleCats.length === 0 && !adding && (
                  <tr>
                    <td colSpan={5} className="table-cell !py-10 text-center !text-faint">
                      {cats?.length ? 'No categories match the selected team' : 'No categories configured — click "Add Category" to start'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="text-xs text-faint">
        Double-click a row to edit inline. Auto Comment ON: AURA auto-posts confident replies, transitions ticket status, and continues the conversation until resolved. OFF: every reply is drafted for a technician to review and post manually.
      </p>
    </div>
  )
}
