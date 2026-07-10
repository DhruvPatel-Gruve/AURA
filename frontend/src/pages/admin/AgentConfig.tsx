import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, CheckCircle } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { useConfigStore } from '@/store/configStore'
import { ITSM_PROVIDER_SHORT_LABELS } from '@/utils/constants'
import type { PlatformConfig } from '@/api/types'

type ConfigKeys = Pick<
  PlatformConfig,
  | 'confidence_threshold'
  | 'abstention_threshold'
  | 'conversation_idle_timeout_hours'
  | 'polling_interval_minutes'
  | 'ingestion_interval_hours'
  | 'collision_timeout_minutes'
  | 'assignment_timeout_minutes'
>

interface SliderFieldProps {
  label:       string
  description: string
  value:       number
  min:         number
  max:         number
  step:        number
  display:     (v: number) => string
  onChange:    (v: number) => void
}

function SliderField({ label, description, value, min, max, step, display, onChange }: SliderFieldProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-sm font-medium text-ink">{label}</label>
          <p className="text-xs text-body mt-0.5">{description}</p>
        </div>
        <span className="text-sm font-mono font-semibold tabular-nums text-accent w-14 text-right">{display(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 appearance-none bg-sunken ring-1 ring-line rounded-full cursor-pointer
                   [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4
                   [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full
                   [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-sm"
      />
      <div className="flex justify-between text-[10px] font-mono tabular-nums text-faint">
        <span>{display(min)}</span>
        <span>{display(max)}</span>
      </div>
    </div>
  )
}

/**
 * Static annotated 0–100% scale showing where the abstention and confidence
 * thresholds sit relative to each other. Purely presentational — driven by
 * the current form values.
 */
function ThresholdScale({ abstention, confidence }: { abstention: number; confidence: number }) {
  const ticks = [
    { label: 'abstain', value: abstention },
    { label: 'auto-post', value: confidence },
  ]
  return (
    <div className="pt-2">
      <p className="overline-label mb-4">Decision Scale</p>
      <div className="relative mx-1 mb-8 mt-1">
        <div className="h-1 bg-sunken ring-1 ring-line rounded" />
        {ticks.map((t) => (
          <div
            key={t.label}
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
            style={{ left: `${Math.min(100, Math.max(0, t.value * 100))}%` }}
          >
            <div className="h-3 w-px bg-faint mx-auto" />
            <span className="absolute left-1/2 -translate-x-1/2 top-4 font-mono text-[10px] tabular-nums text-faint whitespace-nowrap">
              {t.label} {Math.round(t.value * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

interface NumberFieldProps {
  label:       string
  description: string
  value:       number
  min:         number
  unit:        string
  onChange:    (v: number) => void
}

function NumberField({ label, description, value, min, unit, onChange }: NumberFieldProps) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <label className="text-sm font-medium text-ink">{label}</label>
        <p className="text-xs text-body mt-0.5">{description}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type="number"
          min={min}
          value={value}
          onChange={(e) => onChange(Math.max(min, Number(e.target.value)))}
          className="input-base w-20 text-right font-mono tabular-nums"
        />
        <span className="text-sm text-body w-8">{unit}</span>
      </div>
    </div>
  )
}

export default function AgentConfig() {
  const qc = useQueryClient()
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[useConfigStore((s) => s.itsmProvider)]
  const [saved, setSaved]     = useState(false)
  const [local, setLocal]     = useState<ConfigKeys | null>(null)
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data: config, isLoading } = useQuery({
    queryKey: ['admin', 'config'],
    queryFn:  adminApi.getConfig,
  })

  useEffect(() => {
    if (config && !local) {
      setLocal({
        confidence_threshold:      config.confidence_threshold,
        abstention_threshold:      config.abstention_threshold,
        conversation_idle_timeout_hours: config.conversation_idle_timeout_hours,
        polling_interval_minutes:  config.polling_interval_minutes,
        ingestion_interval_hours:  config.ingestion_interval_hours,
        collision_timeout_minutes: config.collision_timeout_minutes,
        assignment_timeout_minutes: config.assignment_timeout_minutes,
      })
    }
  }, [config, local])

  const saveMutation = useMutation({
    mutationFn: (data: Partial<PlatformConfig>) => adminApi.updateConfig(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'config'] })
      setSaved(true)
      if (savedTimer.current) clearTimeout(savedTimer.current)
      savedTimer.current = setTimeout(() => setSaved(false), 3000)
    },
  })

  const update = <K extends keyof ConfigKeys>(key: K, value: ConfigKeys[K]) => {
    setLocal((l) => l ? { ...l, [key]: value } : l)
  }

  const handleSave = () => {
    if (local) saveMutation.mutate(local)
  }

  if (isLoading || !local) {
    return (
      <div className="flex items-center justify-center p-12">
        <LoadingSpinner />
      </div>
    )
  }

  const pct = (v: number) => `${Math.round(v * 100)}%`

  return (
    <div className="space-y-5">
      <PageHeader
        title="Agent Configuration"
        description="Tune AURA's decision thresholds and scheduling intervals"
        actions={
          <>
            {saved && (
              <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <CheckCircle className="h-3.5 w-3.5" />
                Saved
              </span>
            )}
            <button onClick={handleSave} disabled={saveMutation.isPending} className="btn-primary">
              {saveMutation.isPending ? <LoadingSpinner size="sm" /> : <Save className="h-4 w-4" />}
              Save Changes
            </button>
          </>
        }
      />

      {saveMutation.isError && (
        <div className="p-3 rounded-lg spine-critical bg-red-50 dark:bg-red-900/20 text-sm text-red-600 dark:text-red-400">
          Failed to save configuration. Please try again.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Thresholds */}
        <div className="card p-5 space-y-6">
          <h2 className="overline-label border-b border-line pb-3">
            Decision Thresholds
          </h2>
          <SliderField
            label="Confidence Threshold"
            description="Auto-post only when resolution confidence exceeds this value"
            value={local.confidence_threshold}
            min={0.5}
            max={1.0}
            step={0.01}
            display={pct}
            onChange={(v) => update('confidence_threshold', v)}
          />
          <SliderField
            label="Abstention Threshold"
            description="Abstain when the best KB match scores below this value"
            value={local.abstention_threshold}
            min={0.3}
            max={0.9}
            step={0.01}
            display={pct}
            onChange={(v) => update('abstention_threshold', v)}
          />
          <ThresholdScale
            abstention={local.abstention_threshold}
            confidence={local.confidence_threshold}
          />
        </div>

        {/* Intervals */}
        <div className="card p-5 space-y-5">
          <h2 className="overline-label border-b border-line pb-3">
            Scheduling Intervals
          </h2>
          <NumberField
            label={`${providerLabel} Polling Interval`}
            description={`How often to fetch new open tickets from ${providerLabel}`}
            value={local.polling_interval_minutes}
            min={1}
            unit="min"
            onChange={(v) => update('polling_interval_minutes', v)}
          />
          <NumberField
            label="Ingestion Interval"
            description="How often to sync resolved tickets into the knowledge base"
            value={local.ingestion_interval_hours}
            min={1}
            unit="hr"
            onChange={(v) => update('ingestion_interval_hours', v)}
          />
          <NumberField
            label="Collision Timeout"
            description="How long a ticket claim lock remains active without action"
            value={local.collision_timeout_minutes}
            min={5}
            unit="min"
            onChange={(v) => update('collision_timeout_minutes', v)}
          />
          <NumberField
            label="Assignment Timeout"
            description="Reassign to another technician if not acknowledged within this window"
            value={local.assignment_timeout_minutes}
            min={5}
            unit="min"
            onChange={(v) => update('assignment_timeout_minutes', v)}
          />
          <NumberField
            label="Conversation Idle Timeout"
            description="Auto-resolve a ticket after this long with no reply from the reporter"
            value={local.conversation_idle_timeout_hours}
            min={1}
            unit="hr"
            onChange={(v) => update('conversation_idle_timeout_hours', v)}
          />
        </div>
      </div>
    </div>
  )
}
