import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, PauseCircle, PlayCircle, KeyRound, Copy, Check } from 'lucide-react'
import { masterApi } from '@/api/master.api'
import type { TenantSummary, TenantCreate, TenantUpdate } from '@/api/master.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { formatRelativeTime } from '@/utils/formatters'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'

const emptyForm: TenantCreate = {
  name: '', admin_email: '', admin_display_name: '',
}

// One-time reveal of a freshly issued temporary password — the backend
// never returns a plaintext password again after this response, so this
// is the client's only chance to hand it to the tenant.
function CredentialReveal({ email, password }: { email: string; password: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-3">
      <p className="text-sm text-body">
        Share these credentials with the tenant's admin now — this password
        will not be shown again.
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

export default function TenantManagement() {
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<TenantCreate>(emptyForm)
  const [editTenant, setEditTenant] = useState<TenantSummary | null>(null)
  const [editName, setEditName] = useState('')
  const [reveal, setReveal] = useState<{ email: string; password: string } | null>(null)

  const { data: tenants, isLoading } = useQuery({
    queryKey: ['master', 'tenants'],
    queryFn:  masterApi.getTenants,
  })

  const createMutation = useMutation({
    mutationFn: (data: TenantCreate) => masterApi.createTenant(data),
    onSuccess:  (res) => {
      qc.invalidateQueries({ queryKey: ['master', 'tenants'] })
      setCreateOpen(false)
      setForm(emptyForm)
      setReveal({ email: res.admin_email, password: res.temporary_password })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: TenantUpdate }) => masterApi.updateTenant(id, data),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['master', 'tenants'] }); setEditTenant(null) },
  })

  const resetMutation = useMutation({
    mutationFn: (id: string) => masterApi.resetTenantAdmin(id),
    onSuccess:  (res) => setReveal({ email: res.admin_email, password: res.temporary_password }),
  })

  return (
    <div className="space-y-5">
      <PageHeader
        title="Tenants"
        description={tenants ? `${tenants.length} tenant${tenants.length === 1 ? '' : 's'}` : 'Provision and manage client organizations'}
        actions={
          <button onClick={() => setCreateOpen(true)} className="btn-primary">
            <Plus className="h-4 w-4" />
            New Tenant
          </button>
        }
      />

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
                  <th className="table-head">Name</th>
                  <th className="table-head">Admin</th>
                  <th className="table-head">ITSM</th>
                  <th className="table-head">Status</th>
                  <th className="table-head">Setup</th>
                  <th className="table-head">Users</th>
                  <th className="table-head">Created</th>
                  <th className="table-head">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(tenants ?? []).map((t) => (
                  <tr key={t.tenant_id} className="hover:bg-sunken transition-colors">
                    <td className="table-cell font-medium text-ink">{t.name}</td>
                    <td className="table-cell text-body">{t.admin_email ?? '—'}</td>
                    <td className="table-cell text-body">
                      {ITSM_PROVIDER_SHORT_LABELS[t.itsm_provider as 'jira' | 'zendesk'] ?? t.itsm_provider}
                    </td>
                    <td className="table-cell">
                      <Badge tone={t.status === 'active' ? 'success' : 'critical'} dot>
                        {t.status === 'active' ? 'Active' : 'Suspended'}
                      </Badge>
                    </td>
                    <td className="table-cell">
                      <Badge tone={t.setup_complete ? 'success' : 'warn'}>
                        {t.setup_complete ? 'Complete' : 'Pending'}
                      </Badge>
                    </td>
                    <td className="table-cell font-mono text-faint">{t.user_count}</td>
                    <td className="table-cell font-mono text-faint">{formatRelativeTime(t.created_at)}</td>
                    <td className="table-cell">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => { setEditTenant(t); setEditName(t.name) }}
                          className="btn-ghost !px-2 !py-1 text-xs"
                          title="Rename"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => resetMutation.mutate(t.tenant_id)}
                          disabled={!t.admin_email || resetMutation.isPending}
                          className="btn-ghost !px-2 !py-1 text-xs"
                          title="Reset admin password"
                        >
                          <KeyRound className="h-3.5 w-3.5" />
                        </button>
                        {t.status === 'active' ? (
                          <button
                            onClick={() => updateMutation.mutate({ id: t.tenant_id, data: { status: 'suspended' } })}
                            className="btn-ghost !px-2 !py-1 text-xs text-red-500 hover:text-red-600"
                            title="Suspend"
                          >
                            <PauseCircle className="h-3.5 w-3.5" />
                          </button>
                        ) : (
                          <button
                            onClick={() => updateMutation.mutate({ id: t.tenant_id, data: { status: 'active' } })}
                            className="btn-ghost !px-2 !py-1 text-xs text-emerald-600"
                            title="Reactivate"
                          >
                            <PlayCircle className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {(tenants ?? []).length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-10 text-center text-sm text-faint">
                      No tenants yet — create one to get started
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create tenant modal */}
      <Modal open={createOpen} onClose={() => { setCreateOpen(false); setForm(emptyForm) }} title="New Tenant">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-body mb-1">Organization Name</label>
            <input
              type="text"
              className="input-base"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Acme Corp"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Admin Email</label>
            <input
              type="email"
              className="input-base"
              value={form.admin_email}
              onChange={(e) => setForm((f) => ({ ...f, admin_email: e.target.value }))}
              placeholder="admin@acme.com"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-body mb-1">Admin Display Name</label>
            <input
              type="text"
              className="input-base"
              value={form.admin_display_name}
              onChange={(e) => setForm((f) => ({ ...f, admin_display_name: e.target.value }))}
              placeholder="Full Name"
            />
          </div>
          <p className="text-[11px] text-faint">
            The tenant's admin picks their ITSM provider (Jira or Zendesk) and enters its credentials during their own Setup Wizard.
          </p>
          {createMutation.error && (
            <p className="text-xs text-red-500">Failed to create tenant. Check the admin email isn't already registered.</p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => { setCreateOpen(false); setForm(emptyForm) }} className="btn-ghost">
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate(form)}
              disabled={!form.name || !form.admin_email || !form.admin_display_name || createMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending ? <LoadingSpinner size="sm" /> : 'Create Tenant'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Rename tenant modal */}
      <Modal open={!!editTenant} onClose={() => setEditTenant(null)} title="Rename Tenant">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-body mb-1">Organization Name</label>
            <input
              type="text"
              className="input-base"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
            />
          </div>
          {updateMutation.error && (
            <p className="text-xs text-red-500">Update failed. Please try again.</p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setEditTenant(null)} className="btn-ghost">Cancel</button>
            <button
              onClick={() => editTenant && updateMutation.mutate({ id: editTenant.tenant_id, data: { name: editName } })}
              disabled={!editName.trim() || updateMutation.isPending}
              className="btn-primary"
            >
              {updateMutation.isPending ? <LoadingSpinner size="sm" /> : 'Save'}
            </button>
          </div>
        </div>
      </Modal>

      {/* One-time credential reveal — shown after create or a password reset */}
      <Modal open={!!reveal} onClose={() => setReveal(null)} title="Temporary Password Issued">
        {reveal && <CredentialReveal email={reveal.email} password={reveal.password} />}
      </Modal>
    </div>
  )
}
