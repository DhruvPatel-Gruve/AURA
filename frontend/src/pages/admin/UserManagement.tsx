import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, UserX, UserCheck, Search, ArrowUp, ArrowDown, KeyRound, Copy, Check } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatRelativeTime } from '@/utils/formatters'
import { cn } from '@/utils/cn'
import { useConfigStore } from '@/store/configStore'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'
import type { UserPublic, UserCreate, UserUpdate } from '@/api/types'

// One-time reveal of a freshly issued temporary password — the backend
// never returns a plaintext password again after this response, so this
// is the admin's only chance to hand it to the user.
function CredentialReveal({ email, password }: { email: string; password: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-3">
      <p className="text-sm text-body">
        Share these credentials with the user now — this password will not be shown again.
      </p>
      <div className="rounded-lg border border-line bg-sunken p-3 space-y-2 font-mono text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="text-faint">Email</span>
          <span className="text-ink">{email}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-faint">Password</span>
          <span className="text-ink">{password}</span>
        </div>
      </div>
      <button
        onClick={() => {
          navigator.clipboard.writeText(`${email} / ${password}`)
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        }}
        className="btn-secondary w-full"
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        {copied ? 'Copied' : 'Copy to clipboard'}
      </button>
    </div>
  )
}

const ROLES = ['admin', 'manager', 'technician', 'enduser'] as const

const ROLE_LABELS: Record<string, string> = {
  admin: 'Admin', manager: 'Manager', technician: 'Technician', enduser: 'End User',
}

const ROLE_TONES: Record<string, BadgeTone> = {
  admin:      'accent',
  manager:    'info',
  technician: 'neutral',
  enduser:    'neutral',
}

interface UserFormState {
  email: string; display_name: string; password: string; role: string; team_id: string; jira_account_id: string
}

const emptyForm: UserFormState = { email: '', display_name: '', password: '', role: 'technician', team_id: '', jira_account_id: '' }

type SortKey = 'display_name' | 'role' | 'last_login'

function SortableHeader({
  label, column, sortKey, sortDir, onSort,
}: {
  label:   string
  column:  SortKey
  sortKey: SortKey | null
  sortDir: 'asc' | 'desc'
  onSort:  (column: SortKey) => void
}) {
  const active = sortKey === column
  return (
    <th className="table-head">
      <button onClick={() => onSort(column)} className={cn('flex items-center gap-1 hover:text-ink', active && 'text-ink')}>
        {label}
        {active && (sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}

export default function UserManagement() {
  const qc = useQueryClient()
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[useConfigStore((s) => s.itsmProvider)]
  const [createOpen, setCreateOpen] = useState(false)
  const [editUser, setEditUser]     = useState<UserPublic | null>(null)
  const [form, setForm]             = useState<UserFormState>(emptyForm)
  const [editForm, setEditForm]     = useState<Partial<UserUpdate>>({})
  const [resetConfirmUser, setResetConfirmUser] = useState<UserPublic | null>(null)
  const [reveal, setReveal] = useState<{ email: string; password: string } | null>(null)

  const [search, setSearch]         = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | 'active' | 'inactive'>('')
  const [sortKey, setSortKey]       = useState<SortKey | null>(null)
  const [sortDir, setSortDir]       = useState<'asc' | 'desc'>('asc')

  const { data: users, isLoading } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn:  adminApi.getUsers,
  })

  const handleSort = (column: SortKey) => {
    if (sortKey === column) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(column); setSortDir('asc') }
  }

  const visibleUsers = (users ?? [])
    .filter((u) => !roleFilter || u.role === roleFilter)
    .filter((u) => !statusFilter || (statusFilter === 'active' ? u.is_active : !u.is_active))
    .filter((u) => {
      const q = search.trim().toLowerCase()
      return !q || u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    })
    .sort((a, b) => {
      if (!sortKey) return 0
      let cmp = 0
      if (sortKey === 'display_name') cmp = a.display_name.localeCompare(b.display_name)
      else if (sortKey === 'role') cmp = a.role.localeCompare(b.role)
      else cmp = (a.last_login ?? '').localeCompare(b.last_login ?? '')
      return sortDir === 'asc' ? cmp : -cmp
    })

  const createMutation = useMutation({
    mutationFn: (data: UserCreate) => adminApi.createUser(data),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); setCreateOpen(false); setForm(emptyForm) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UserUpdate }) => adminApi.updateUser(id, data),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); setEditUser(null) },
  })

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => adminApi.updateUser(id, { is_active: false }),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  })

  const reactivateMutation = useMutation({
    mutationFn: (id: string) => adminApi.updateUser(id, { is_active: true }),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  })

  const resetPasswordMutation = useMutation({
    mutationFn: (id: string) => adminApi.resetUserPassword(id),
    onSuccess:  (res) => { setResetConfirmUser(null); setReveal({ email: res.email, password: res.temporary_password }) },
  })

  const openEdit = (user: UserPublic) => {
    setEditUser(user)
    setEditForm({
      email: user.email,
      display_name: user.display_name,
      role: user.role,
      is_active: user.is_active,
      team_id: user.team_id ?? '',
      jira_account_id: user.jira_account_id ?? '',
    })
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="User Management"
        description={users ? `${visibleUsers.length} of ${users.length} users` : 'Manage accounts and roles'}
        actions={
          <button onClick={() => setCreateOpen(true)} className="btn-primary">
            <Plus className="h-4 w-4" />
            Add User
          </button>
        }
      />

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or email…"
            className="input-base pl-8 w-56 text-sm"
          />
        </div>
        <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} className="input-base w-40 text-sm">
          <option value="">All roles</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          className="input-base w-36 text-sm"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <LoadingSpinner />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10">
                <tr>
                  <SortableHeader label="Name" column="display_name" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <th className="table-head">Email</th>
                  <SortableHeader label="Role" column="role" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <th className="table-head">Status</th>
                  <SortableHeader label="Last Login" column="last_login" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <th className="table-head">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleUsers.map((u) => (
                  <tr key={u.user_id} className="hover:bg-sunken transition-colors">
                    <td className="table-cell font-medium text-ink">
                      {u.display_name}
                    </td>
                    <td className="table-cell text-body">{u.email}</td>
                    <td className="table-cell">
                      <Badge tone={ROLE_TONES[u.role] ?? 'neutral'}>
                        {ROLE_LABELS[u.role] ?? u.role}
                      </Badge>
                    </td>
                    <td className="table-cell">
                      <Badge tone={u.is_active ? 'success' : 'neutral'} dot>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="table-cell font-mono text-faint">
                      {u.last_login ? formatRelativeTime(u.last_login) : '—'}
                    </td>
                    <td className="table-cell">
                      <div className="flex items-center gap-1">
                        <button onClick={() => openEdit(u)} className="btn-ghost !px-2 !py-1 text-xs">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => setResetConfirmUser(u)}
                          className="btn-ghost !px-2 !py-1 text-xs"
                          title="Reset password"
                        >
                          <KeyRound className="h-3.5 w-3.5" />
                        </button>
                        {u.is_active ? (
                          <button
                            onClick={() => deactivateMutation.mutate(u.user_id)}
                            className="btn-ghost !px-2 !py-1 text-xs text-red-500 hover:text-red-600"
                            title="Deactivate"
                          >
                            <UserX className="h-3.5 w-3.5" />
                          </button>
                        ) : (
                          <button
                            onClick={() => reactivateMutation.mutate(u.user_id)}
                            className="btn-ghost !px-2 !py-1 text-xs text-emerald-600"
                            title="Reactivate"
                          >
                            <UserCheck className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {visibleUsers.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-faint">
                      {users?.length ? 'No users match the current filters' : 'No users found'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create user modal */}
      <Modal open={createOpen} onClose={() => { setCreateOpen(false); setForm(emptyForm) }} title="Add User">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-body mb-1">Email</label>
            <input
              type="email"
              className="input-base"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              placeholder="user@company.com"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Display Name</label>
            <input
              type="text"
              className="input-base"
              value={form.display_name}
              onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
              placeholder="Full Name"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Temporary Password</label>
            <input
              type="password"
              className="input-base"
              value={form.password}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              placeholder="Min 8 characters"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Role</label>
            <select
              className="input-base"
              value={form.role}
              onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{ROLE_LABELS[r]}</option>
              ))}
            </select>
          </div>
          {form.role === 'technician' && (
            <>
              <div>
                <label className="block text-xs font-medium text-body mb-1">
                  Team <span className="text-faint font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  className="input-base"
                  value={form.team_id}
                  onChange={(e) => setForm((f) => ({ ...f, team_id: e.target.value }))}
                  placeholder="e.g. network-team — must match a category's team to receive assignments"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-body mb-1">
                  {providerLabel} Account ID <span className="text-faint font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  className="input-base"
                  value={form.jira_account_id}
                  onChange={(e) => setForm((f) => ({ ...f, jira_account_id: e.target.value }))}
                  placeholder="Leave blank to auto-resolve by email on first assignment"
                />
              </div>
            </>
          )}
          {createMutation.error && (
            <p className="text-xs text-red-500">Failed to create user. Please try again.</p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => { setCreateOpen(false); setForm(emptyForm) }} className="btn-ghost">
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate({
                email: form.email,
                display_name: form.display_name,
                password: form.password,
                role: form.role,
                team_id: form.team_id.trim() || undefined,
                jira_account_id: form.jira_account_id.trim() || undefined,
              })}
              disabled={!form.email || !form.display_name || !form.password || createMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending ? <LoadingSpinner size="sm" /> : 'Create User'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Edit user modal */}
      <Modal open={!!editUser} onClose={() => setEditUser(null)} title="Edit User">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-body mb-1">Email</label>
            <input
              type="email"
              className="input-base"
              value={editForm.email ?? ''}
              onChange={(e) => setEditForm((f) => ({ ...f, email: e.target.value }))}
            />
            <p className="text-[11px] text-faint mt-1">
              Changing this clears any linked {providerLabel} account — it'll auto-resolve again by the new email.
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Display Name</label>
            <input
              type="text"
              className="input-base"
              value={editForm.display_name ?? ''}
              onChange={(e) => setEditForm((f) => ({ ...f, display_name: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Role</label>
            <select
              className="input-base"
              value={editForm.role ?? 'technician'}
              onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{ROLE_LABELS[r]}</option>
              ))}
            </select>
          </div>
          {editForm.role === 'technician' && (
            <>
              <div>
                <label className="block text-xs font-medium text-body mb-1">
                  Team <span className="text-faint font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  className="input-base"
                  value={editForm.team_id ?? ''}
                  onChange={(e) => setEditForm((f) => ({ ...f, team_id: e.target.value }))}
                  placeholder="e.g. network-team — must match a category's team to receive assignments"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-body mb-1">
                  {providerLabel} Account ID <span className="text-faint font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  className="input-base"
                  value={editForm.jira_account_id ?? ''}
                  onChange={(e) => setEditForm((f) => ({ ...f, jira_account_id: e.target.value }))}
                  placeholder="Leave blank to auto-resolve by email on first assignment"
                />
              </div>
            </>
          )}
          {updateMutation.error && (
            <p className="text-xs text-red-500">Update failed. Please try again.</p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setEditUser(null)} className="btn-ghost">Cancel</button>
            <button
              onClick={() => {
                if (!editUser) return
                // Only send email if it actually changed — the backend clears
                // jira_account_id whenever email is present in the payload,
                // so sending it unchanged on every edit would wipe it needlessly.
                const { email, ...rest } = editForm
                const data = email && email !== editUser.email ? { ...rest, email } : rest
                updateMutation.mutate({ id: editUser.user_id, data })
              }}
              disabled={updateMutation.isPending}
              className="btn-primary"
            >
              {updateMutation.isPending ? <LoadingSpinner size="sm" /> : 'Save'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Reset password confirmation */}
      <Modal open={!!resetConfirmUser} onClose={() => setResetConfirmUser(null)} title="Reset Password" size="sm">
        <div className="space-y-4">
          <p className="text-sm text-body">
            This immediately replaces <span className="font-medium text-ink">{resetConfirmUser?.display_name}</span>'s
            password with a new one-time temporary password and signs them out everywhere. Their current password will
            stop working right away.
          </p>
          {resetPasswordMutation.error && (
            <p className="text-xs text-red-500">Failed to reset password. Please try again.</p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setResetConfirmUser(null)} className="btn-ghost">Cancel</button>
            <button
              onClick={() => resetConfirmUser && resetPasswordMutation.mutate(resetConfirmUser.user_id)}
              disabled={resetPasswordMutation.isPending}
              className="btn-primary"
            >
              {resetPasswordMutation.isPending ? <LoadingSpinner size="sm" /> : 'Reset Password'}
            </button>
          </div>
        </div>
      </Modal>

      {/* One-time credential reveal — shown after a successful reset */}
      <Modal open={!!reveal} onClose={() => setReveal(null)} title="Temporary Password Issued">
        {reveal && <CredentialReveal email={reveal.email} password={reveal.password} />}
      </Modal>
    </div>
  )
}
