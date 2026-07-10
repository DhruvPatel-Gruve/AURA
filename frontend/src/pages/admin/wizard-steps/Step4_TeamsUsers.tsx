import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Eye, EyeOff, UserCircle2 } from 'lucide-react'
import { cn } from '@/utils/cn'

export type UserRole = 'technician' | 'manager'

export interface UserRow {
  id:           string
  email:        string
  display_name: string
  role:         UserRole
  password:     string
}

export interface Step4Data {
  users: UserRow[]
}

const genId = () => Math.random().toString(36).slice(2, 9)

interface Props {
  initialData?: Partial<Step4Data>
  onChange: (data: Step4Data, valid: boolean) => void
}

function isValidEmail(email: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

function isRowValid(r: UserRow) {
  return isValidEmail(r.email) && r.display_name.trim() !== '' && r.password.length >= 8
}

export default function Step4_TeamsUsers({ initialData, onChange }: Props) {
  const [rows,       setRows]       = useState<UserRow[]>(initialData?.users ?? [])
  const [showPw,     setShowPw]     = useState<Record<string, boolean>>({})

  const notify = useCallback(
    (r: UserRow[]) => {
      const valid = r.length === 0 || r.every(isRowValid)
      onChange({ users: r }, valid)
    },
    [onChange],
  )

  useEffect(() => { notify(rows) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const addRow = () => {
    setRows((prev) => {
      const next = [...prev, { id: genId(), email: '', display_name: '', role: 'technician' as UserRole, password: '' }]
      notify(next)
      return next
    })
  }

  const updateRow = (id: string, field: keyof Omit<UserRow, 'id'>, value: string) => {
    setRows((prev) => {
      const next = prev.map((r) => r.id === id ? { ...r, [field]: value } : r)
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

  const togglePw = (id: string) =>
    setShowPw((prev) => ({ ...prev, [id]: !prev[id] }))

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Teams & Users
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Add your technicians and managers. You can skip this step and add users later in Admin → Users.
        </p>
      </div>

      {rows.length === 0 ? (
        <div className="card p-8 flex flex-col items-center gap-3 text-center">
          <UserCircle2 className="h-10 w-10 text-line" />
          <div>
            <p className="text-sm font-medium text-body">No users added yet</p>
            <p className="text-xs text-faint mt-0.5">
              You can add users now or come back to this after setup.
            </p>
          </div>
          <button type="button" onClick={addRow} className="btn-primary mt-1">
            <Plus className="h-4 w-4" />
            Add first user
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((row) => {
            const valid = isRowValid(row)
            return (
              <div key={row.id} className={cn('card p-4 space-y-3', !valid && row.email && 'spine-warn')}>
                <div className="flex items-center justify-between">
                  <span className="overline-label">
                    {row.display_name || 'New user'}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeRow(row.id)}
                    className="h-7 w-7 flex items-center justify-center rounded-lg
                               text-faint hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20
                               transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {/* Display name */}
                  <div>
                    <label className="block text-xs font-medium text-body mb-1">
                      Display name
                    </label>
                    <input
                      type="text"
                      value={row.display_name}
                      onChange={(e) => updateRow(row.id, 'display_name', e.target.value)}
                      placeholder="Jane Smith"
                      className="input-base"
                    />
                  </div>

                  {/* Role */}
                  <div>
                    <label className="block text-xs font-medium text-body mb-1">
                      Role
                    </label>
                    <select
                      value={row.role}
                      onChange={(e) => updateRow(row.id, 'role', e.target.value as UserRole)}
                      className="input-base"
                    >
                      <option value="technician">Technician</option>
                      <option value="manager">Manager</option>
                    </select>
                  </div>

                  {/* Email */}
                  <div>
                    <label className="block text-xs font-medium text-body mb-1">
                      Email
                    </label>
                    <input
                      type="email"
                      value={row.email}
                      onChange={(e) => updateRow(row.id, 'email', e.target.value)}
                      placeholder="jane@company.com"
                      className={cn(
                        'input-base',
                        row.email && !isValidEmail(row.email) && 'border-red-300 dark:border-red-700',
                      )}
                    />
                  </div>

                  {/* Password */}
                  <div>
                    <label className="block text-xs font-medium text-body mb-1">
                      Initial password
                    </label>
                    <div className="relative">
                      <input
                        type={showPw[row.id] ? 'text' : 'password'}
                        value={row.password}
                        onChange={(e) => updateRow(row.id, 'password', e.target.value)}
                        placeholder="Min. 8 characters"
                        className={cn(
                          'input-base pr-9',
                          row.password && row.password.length < 8 && 'border-red-300 dark:border-red-700',
                        )}
                      />
                      <button
                        type="button"
                        onClick={() => togglePw(row.id)}
                        tabIndex={-1}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-faint hover:text-body"
                      >
                        {showPw[row.id] ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}

          <button type="button" onClick={addRow} className="btn-ghost w-full">
            <Plus className="h-4 w-4" />
            Add another user
          </button>
        </div>
      )}
    </div>
  )
}
