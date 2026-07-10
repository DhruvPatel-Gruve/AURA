import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { PlusCircle, CheckCircle, ArrowLeft, Loader2 } from 'lucide-react'
import { ticketsApi } from '@/api/tickets.api'
import { useConfigStore } from '@/store/configStore'
import { ITSM_PROVIDER_LABELS } from '@/utils/constants'

const CATEGORIES = [
  'Access & Permissions',
  'Hardware',
  'Software',
  'Network & Connectivity',
  'Email & Collaboration',
  'Security',
  'Account Management',
  'General',
]

const PRIORITY_HINT = [
  { value: '', label: 'Select urgency…' },
  { value: 'low',      label: 'Low — not urgent, can wait' },
  { value: 'medium',   label: 'Medium — affecting my work' },
  { value: 'high',     label: 'High — blocking me right now' },
  { value: 'critical', label: 'Critical — full outage / major impact' },
]

interface FormState {
  summary:       string
  description:   string
  category_hint: string
  priority_hint: string
}

export default function SubmitTicket() {
  const navigate = useNavigate()
  const providerLabel = ITSM_PROVIDER_LABELS[useConfigStore((s) => s.itsmProvider)]
  const [form, setForm] = useState<FormState>({
    summary:       '',
    description:   '',
    category_hint: '',
    priority_hint: '',
  })
  const [submitted, setSubmitted] = useState<{ ticket_id: string } | null>(null)

  const { mutate, isPending, error } = useMutation({
    mutationFn: () =>
      ticketsApi.submitTicket({
        summary:       form.summary.trim(),
        description:   form.description.trim(),
        category_hint: form.category_hint || undefined,
      }),
    onSuccess: (data) => setSubmitted(data),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.summary.trim() || !form.description.trim()) return
    mutate()
  }

  const set = (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }))

  if (submitted) {
    return (
      <div className="max-w-lg mx-auto">
        <div className="card p-8 text-center space-y-4">
          <CheckCircle className="h-10 w-10 text-emerald-600 dark:text-emerald-400 mx-auto" />
          <div>
            <p className="text-base font-semibold text-ink">Ticket submitted</p>
            <p className="text-sm text-body mt-1">
              Your ticket <span className="font-mono font-medium text-ink">{submitted.ticket_id}</span> has been created in {providerLabel}.
            </p>
          </div>
          <p className="text-xs text-faint">
            AURA will triage it shortly. If it can resolve it automatically, you'll receive a comment on the ticket within minutes.
          </p>
          <div className="flex gap-3 justify-center pt-2">
            <button
              onClick={() => { setSubmitted(null); setForm({ summary: '', description: '', category_hint: '', priority_hint: '' }) }}
              className="btn-secondary text-sm"
            >
              Submit another
            </button>
            <button
              onClick={() => navigate('/enduser/chat')}
              className="btn-primary text-sm"
            >
              Ask AURA
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/enduser')}
          className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-sunken transition-colors shrink-0"
        >
          <ArrowLeft className="h-4 w-4 text-faint" />
        </button>
        <div>
          <h1 className="font-display text-xl font-semibold text-ink leading-7">Submit a Support Ticket</h1>
          <p className="text-sm text-body mt-0.5">
            Describe your issue and AURA will triage it automatically.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="card p-6 space-y-5">
        {/* Summary */}
        <div className="space-y-1.5">
          <label className="block text-sm font-medium text-body">
            Summary <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={form.summary}
            onChange={set('summary')}
            placeholder="One-line description of the issue"
            maxLength={200}
            className="input-base"
            required
          />
          <p className="text-xs text-faint font-mono tabular-nums">{form.summary.length}/200</p>
        </div>

        {/* Description */}
        <div className="space-y-1.5">
          <label className="block text-sm font-medium text-body">
            Description <span className="text-red-500">*</span>
          </label>
          <textarea
            value={form.description}
            onChange={set('description')}
            placeholder="What is happening? When did it start? What have you already tried?"
            rows={6}
            className="input-base resize-none"
            required
          />
          <p className="text-xs text-faint">More detail helps AURA find the right resolution faster.</p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {/* Category hint */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-body">Category</label>
            <select value={form.category_hint} onChange={set('category_hint')} className="input-base">
              <option value="">Select a category…</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Urgency (informational only — not sent to backend) */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-body">Urgency</label>
            <select value={form.priority_hint} onChange={set('priority_hint')} className="input-base">
              {PRIORITY_HINT.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            {(error as { response?: { data?: { detail?: string } } })
              ?.response?.data?.detail ?? 'Failed to submit ticket. Please try again.'}
          </p>
        )}

        <div className="flex items-center justify-end gap-3 pt-1">
          <button type="button" onClick={() => navigate('/enduser')} className="btn-ghost">
            Cancel
          </button>
          <button
            type="submit"
            disabled={isPending || !form.summary.trim() || !form.description.trim()}
            className="btn-primary flex items-center gap-2"
          >
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlusCircle className="h-4 w-4" />}
            {isPending ? 'Submitting…' : 'Submit Ticket'}
          </button>
        </div>
      </form>
    </div>
  )
}
