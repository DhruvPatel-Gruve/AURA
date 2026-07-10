import { useState } from 'react'
import { Eye, EyeOff, Check } from 'lucide-react'
import { authApi } from '@/api/auth.api'
import { Modal } from '@/components/ui/Modal'
import { Badge } from '@/components/ui/Badge'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'

const ROLE_LABELS: Record<string, string> = {
  master_admin: 'Master Admin',
  admin:        'Administrator',
  manager:      'Manager',
  technician:   'Technician',
  enduser:      'End User',
}

interface Props {
  open:        boolean
  onClose:     () => void
  displayName: string | null
  email:       string | null
  role:        string | null
}

export function AccountSettingsModal({ open, onClose, displayName, email, role }: Props) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword,     setNewPassword]     = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPw,          setShowPw]          = useState(false)
  const [submitting,      setSubmitting]      = useState(false)
  const [error,           setError]           = useState<string | null>(null)
  const [success,         setSuccess]         = useState(false)

  const reset = () => {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError(null)
    setSuccess(false)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleSubmit = async () => {
    setError(null)
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match.')
      return
    }

    setSubmitting(true)
    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password:      newPassword,
      })
      setSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Failed to change password'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Account Settings">
      <div className="space-y-6">
        {/* Account info */}
        <div className="space-y-2">
          <p className="overline-label text-faint">Account</p>
          <div className="rounded-lg border border-line bg-sunken p-3 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-body">Name</span>
              <span className="text-sm text-ink font-medium">{displayName ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-body">Email</span>
              <span className="text-sm text-ink font-mono truncate max-w-[220px]">{email ?? '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-body">Role</span>
              <Badge tone="accent">{role ? (ROLE_LABELS[role] ?? role) : '—'}</Badge>
            </div>
          </div>
        </div>

        {/* Change password */}
        <div className="space-y-3">
          <p className="overline-label text-faint">Change Password</p>

          <div>
            <label className="block text-xs font-medium text-body mb-1">Current Password</label>
            <input
              type={showPw ? 'text' : 'password'}
              className="input-base"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-body mb-1">New Password</label>
            <input
              type={showPw ? 'text' : 'password'}
              className="input-base"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Min 8 characters"
              autoComplete="new-password"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-body mb-1">Re-enter New Password</label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'}
                className="input-base pr-10"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-body"
                tabIndex={-1}
              >
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20
                          border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
          {success && (
            <p className="flex items-center gap-1.5 text-sm text-emerald-700 dark:text-emerald-400
                          bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800
                          rounded-lg px-3 py-2">
              <Check className="h-4 w-4 shrink-0" />
              Password changed. You'll need to log in again on any other devices.
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button onClick={handleClose} className="btn-ghost">Close</button>
            <button
              onClick={handleSubmit}
              disabled={!currentPassword || !newPassword || !confirmPassword || submitting}
              className="btn-primary"
            >
              {submitting ? <LoadingSpinner size="sm" /> : 'Change Password'}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  )
}
