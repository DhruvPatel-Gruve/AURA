import { useState, useEffect, useCallback } from 'react'
import { Loader2, Eye, EyeOff } from 'lucide-react'
import { setupApi } from '@/api/setup.api'
import { Badge } from '@/components/ui/Badge'

export interface Step4ZendeskData {
  subdomain:  string
  api_email:  string
  api_token:  string
  tested:     boolean
  ticket_count?: number
}

interface Props {
  initialData?: Partial<Step4ZendeskData>
  onChange: (data: Step4ZendeskData, valid: boolean) => void
}

export default function Step4_ZendeskConnection({ initialData, onChange }: Props) {
  const [form, setForm] = useState<Omit<Step4ZendeskData, 'tested' | 'ticket_count'>>({
    subdomain: initialData?.subdomain ?? '',
    api_email: initialData?.api_email ?? '',
    api_token: initialData?.api_token ?? '',
  })
  const [tested,       setTested]       = useState(initialData?.tested ?? false)
  const [ticketCount,  setTicketCount]  = useState<number | undefined>(initialData?.ticket_count)
  const [testing,      setTesting]      = useState(false)
  const [testError,    setTestError]    = useState<string | null>(null)
  const [showToken,    setShowToken]    = useState(false)

  const notify = useCallback(
    (f: typeof form, t: boolean, tc?: number) => {
      // api_token is deliberately omitted — it's persisted encrypted by
      // /setup/test-zendesk directly on a successful test, and must never
      // sit in plaintext in wizard_progress (which is what this object feeds).
      const { api_token: _omit, ...safe } = f
      onChange({ ...safe, api_token: '', tested: t, ticket_count: tc }, t)
    },
    [onChange],
  )

  // Notify parent on mount
  useEffect(() => {
    notify(form, tested, ticketCount)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleField = (field: keyof typeof form, value: string) => {
    const next = { ...form, [field]: value }
    setForm(next)
    setTested(false)         // any edit invalidates the test
    setTestError(null)
    notify(next, false)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestError(null)
    try {
      const res = await setupApi.testZendesk({
        subdomain: form.subdomain.trim(),
        api_email: form.api_email.trim(),
        api_token: form.api_token.trim(),
      })
      if (res.success) {
        setTested(true)
        setTicketCount(res.ticket_count)
        notify(form, true, res.ticket_count)
      } else {
        setTestError(res.error ?? 'Connection failed')
        notify(form, false)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Could not reach Zendesk'
      setTestError(msg)
      notify(form, false)
    } finally {
      setTesting(false)
    }
  }

  const allFilled = Object.values(form).every((v) => v.trim() !== '')

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Zendesk Connection
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Connect AURA to your Zendesk workspace.
        </p>
      </div>

      <div className="card p-5 space-y-4">
        {/* Subdomain */}
        <div>
          <label className="block text-sm font-medium text-body mb-1.5">
            Subdomain
          </label>
          <input
            type="text"
            value={form.subdomain}
            onChange={(e) => handleField('subdomain', e.target.value)}
            placeholder="your-company"
            className="input-base font-mono"
          />
          <p className="mt-1 text-xs text-faint">
            The part before .zendesk.com in your workspace URL
          </p>
        </div>

        {/* API email */}
        <div>
          <label className="block text-sm font-medium text-body mb-1.5">
            API account email
          </label>
          <input
            type="email"
            value={form.api_email}
            onChange={(e) => handleField('api_email', e.target.value)}
            placeholder="admin@company.com"
            className="input-base"
          />
        </div>

        {/* API token */}
        <div>
          <label className="block text-sm font-medium text-body mb-1.5">
            API token
          </label>
          <div className="relative">
            <input
              type={showToken ? 'text' : 'password'}
              value={form.api_token}
              onChange={(e) => handleField('api_token', e.target.value)}
              placeholder="••••••••••••••••••••"
              className="input-base pr-10"
            />
            <button
              type="button"
              onClick={() => setShowToken((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-body"
              tabIndex={-1}
            >
              {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-1 text-xs text-faint">
            Generate at Zendesk Admin Center → Apps and integrations → APIs
          </p>
        </div>

        {/* Test result */}
        {tested && (
          <div className="flex items-center gap-2.5 rounded-lg bg-sunken border border-line px-3.5 py-2.5">
            <Badge tone="success" dot>Connected</Badge>
            <span className="text-sm text-body font-mono tabular-nums">
              {ticketCount?.toLocaleString() ?? 0} resolved tickets available
            </span>
          </div>
        )}

        {testError && (
          <div className="flex items-start gap-2.5 rounded-lg bg-sunken border border-line px-3.5 py-2.5">
            <Badge tone="critical" dot>Failed</Badge>
            <span className="text-sm text-body font-mono">{testError}</span>
          </div>
        )}

        {/* Test button */}
        <button
          type="button"
          onClick={handleTest}
          disabled={!allFilled || testing}
          className="btn-secondary w-full"
        >
          {testing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Testing connection…
            </>
          ) : (
            'Test Connection'
          )}
        </button>
      </div>

      {!tested && (
        <p className="text-xs text-faint text-center">
          You must successfully test the connection before continuing.
        </p>
      )}
    </div>
  )
}
