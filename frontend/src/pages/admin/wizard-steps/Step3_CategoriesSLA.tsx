import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { cn } from '@/utils/cn'

export interface CategoryRow {
  id:                   string
  name:                 string
  sla_minutes:          number
  auto_comment_enabled: boolean
}

export interface Step3Data {
  categories: CategoryRow[]
}

const DEFAULT_CATEGORIES: Omit<CategoryRow, 'id'>[] = [
  { name: 'Network',  sla_minutes: 240, auto_comment_enabled: false },
  { name: 'Hardware', sla_minutes: 480, auto_comment_enabled: false },
  { name: 'Software', sla_minutes: 240, auto_comment_enabled: false },
  { name: 'Access',   sla_minutes: 120, auto_comment_enabled: false },
  { name: 'Security', sla_minutes: 60,  auto_comment_enabled: false },
  { name: 'Other',    sla_minutes: 480, auto_comment_enabled: false },
]

const genId = () => Math.random().toString(36).slice(2, 9)

const toDisplay = (minutes: number) => {
  if (minutes < 60)  return `${minutes}m`
  if (minutes % 60 === 0) return `${minutes / 60}h`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0',
        checked ? 'bg-accent' : 'bg-line',
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

interface Props {
  initialData?: Partial<Step3Data>
  onChange: (data: Step3Data, valid: boolean) => void
}

export default function Step3_CategoriesSLA({ initialData, onChange }: Props) {
  const [rows, setRows] = useState<CategoryRow[]>(() => {
    if (initialData?.categories?.length) return initialData.categories
    return DEFAULT_CATEGORIES.map((c) => ({ ...c, id: genId() }))
  })

  const notify = useCallback(
    (r: CategoryRow[]) => {
      onChange({ categories: r }, r.length > 0 && r.every((c) => c.name.trim() !== ''))
    },
    [onChange],
  )

  useEffect(() => { notify(rows) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const updateRow = (id: string, field: keyof Omit<CategoryRow, 'id'>, value: string | number | boolean) => {
    setRows((prev) => {
      const next = prev.map((r) => r.id === id ? { ...r, [field]: value } : r)
      notify(next)
      return next
    })
  }

  const addRow = () => {
    setRows((prev) => {
      const next = [...prev, { id: genId(), name: '', sla_minutes: 240, auto_comment_enabled: false }]
      notify(next)
      return next
    })
  }

  const removeRow = (id: string) => {
    setRows((prev) => {
      const next = prev.filter((r) => r.id !== id)
      notify(next)
      return next
    })
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Categories & SLA
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Define ticket categories, SLA targets, and whether AURA auto-comments for each. You can edit these later in Admin → Categories.
        </p>
      </div>

      <div className="card overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_100px_120px_40px] gap-3 px-4 py-2.5
                        bg-sunken
                        border-b border-line">
          <span className="overline-label">Category</span>
          <span className="overline-label">SLA</span>
          <span className="overline-label">Auto Comment</span>
          <span />
        </div>

        {/* Rows */}
        <div className="divide-y divide-line">
          {rows.map((row) => (
            <div
              key={row.id}
              className="grid grid-cols-[1fr_100px_120px_40px] gap-3 items-center px-4 py-2.5"
            >
              {/* Name */}
              <input
                type="text"
                value={row.name}
                onChange={(e) => updateRow(row.id, 'name', e.target.value)}
                placeholder="e.g. Network"
                className={cn(
                  'input-base',
                  row.name.trim() === '' && 'border-red-300 dark:border-red-700',
                )}
              />

              {/* SLA — display as hours, store as minutes */}
              <div className="relative">
                <input
                  type="number"
                  min={15}
                  step={15}
                  value={row.sla_minutes}
                  onChange={(e) => updateRow(row.id, 'sla_minutes', Math.max(15, Number(e.target.value)))}
                  className="input-base pr-8 text-right font-mono tabular-nums"
                />
                <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-faint pointer-events-none">
                  min
                </span>
                <span className="absolute -bottom-4 right-0 text-[10px] font-mono text-faint">
                  {toDisplay(row.sla_minutes)}
                </span>
              </div>

              {/* Auto comment toggle */}
              <ToggleSwitch
                checked={row.auto_comment_enabled}
                onChange={(v) => updateRow(row.id, 'auto_comment_enabled', v)}
              />

              {/* Delete */}
              <button
                type="button"
                onClick={() => removeRow(row.id)}
                className="h-8 w-8 flex items-center justify-center rounded-lg
                           text-faint hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20
                           transition-colors"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>

        {/* Add row */}
        <div className="px-4 py-3 border-t border-line">
          <button
            type="button"
            onClick={addRow}
            className="btn-ghost text-xs gap-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            Add category
          </button>
        </div>
      </div>

      <p className="text-xs text-faint">
        Auto Comment ON: AURA auto-posts confident replies, transitions ticket status, and continues the conversation until resolved. OFF: every reply is drafted for a technician to review and post manually.
      </p>
    </div>
  )
}
