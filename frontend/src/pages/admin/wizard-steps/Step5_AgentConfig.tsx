import { useState, useEffect, useCallback } from 'react'
import { Info } from 'lucide-react'
import { cn } from '@/utils/cn'
import { ITSM_PROVIDER_SHORT_LABELS, type ItsmProvider } from '@/utils/constants'

export interface Step5Data {
  confidence_threshold:            number
  abstention_threshold:            number
  conversation_idle_timeout_hours: number
  polling_interval_minutes:        number
  collision_timeout_minutes:       number
}

const DEFAULTS: Step5Data = {
  confidence_threshold:            0.90,
  abstention_threshold:            0.60,
  conversation_idle_timeout_hours: 24,
  polling_interval_minutes:        5,
  collision_timeout_minutes:       30,
}

interface SliderFieldProps {
  label:   string
  hint:    string
  value:   number
  min:     number
  max:     number
  step:    number
  format:  (v: number) => string
  onChange: (v: number) => void
}

function SliderField({ label, hint, value, min, max, step, format, onChange }: SliderFieldProps) {
  const pct = ((value - min) / (max - min)) * 100

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-body">{label}</label>
        <span className="font-mono text-sm font-medium text-accent tabular-nums">{format(value)}</span>
      </div>
      <div className="relative">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className={cn(
            'w-full h-1.5 rounded-full appearance-none cursor-pointer',
            'bg-line',
            '[&::-webkit-slider-thumb]:appearance-none',
            '[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4',
            '[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent',
            '[&::-webkit-slider-thumb]:cursor-pointer',
            '[&::-webkit-slider-thumb]:shadow-sm',
          )}
          style={{
            background: `linear-gradient(to right, rgb(var(--accent)) ${pct}%, rgb(var(--line)) ${pct}%)`,
          }}
        />
      </div>
      <p className="text-xs text-faint">{hint}</p>
    </div>
  )
}

interface NumberFieldProps {
  label:   string
  hint:    string
  value:   number
  min:     number
  max:     number
  unit:    string
  onChange: (v: number) => void
}

function NumberField({ label, hint, value, min, max, unit, onChange }: NumberFieldProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-body">{label}</label>
      </div>
      <div className="relative">
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
          className="input-base pr-12 font-mono tabular-nums"
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-faint pointer-events-none">
          {unit}
        </span>
      </div>
      <p className="text-xs text-faint">{hint}</p>
    </div>
  )
}

interface Props {
  initialData?: Partial<Step5Data>
  provider?: ItsmProvider
  onChange: (data: Step5Data, valid: boolean) => void
}

export default function Step5_AgentConfig({ initialData, provider = 'jira', onChange }: Props) {
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[provider]
  const [cfg, setCfg] = useState<Step5Data>({ ...DEFAULTS, ...initialData })

  const notify = useCallback(
    (c: Step5Data) => onChange(c, true),
    [onChange],
  )

  useEffect(() => { notify(cfg) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (field: keyof Step5Data, value: number) => {
    setCfg((prev) => {
      const next = { ...prev, [field]: value }
      notify(next)
      return next
    })
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Agent Configuration
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Tune the agent pipeline thresholds. Defaults are pre-filled with recommended values for this POC.
        </p>
      </div>

      {/* Thresholds */}
      <div className="card p-5 space-y-6">
        <h3 className="overline-label">
          Confidence thresholds
        </h3>

        <SliderField
          label="Auto-post threshold"
          hint={`Suggestions at or above this score are posted to ${providerLabel} automatically.`}
          value={cfg.confidence_threshold}
          min={0.5} max={1} step={0.01}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={(v) => set('confidence_threshold', v)}
        />

        <SliderField
          label="Abstention threshold"
          hint="If the top Qdrant result scores below this, the LLM is never called and the ticket is flagged."
          value={cfg.abstention_threshold}
          min={0.3} max={0.9} step={0.01}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={(v) => set('abstention_threshold', v)}
        />

      </div>

      {/* Timing */}
      <div className="card p-5 space-y-5">
        <h3 className="overline-label">
          Timing
        </h3>

        <NumberField
          label={`${providerLabel} polling interval`}
          hint={`How often AURA checks ${providerLabel} for new open tickets.`}
          value={cfg.polling_interval_minutes}
          min={1} max={60} unit="min"
          onChange={(v) => set('polling_interval_minutes', v)}
        />

        <NumberField
          label="Collision claim timeout"
          hint="A ticket claim expires after this many minutes of inactivity."
          value={cfg.collision_timeout_minutes}
          min={5} max={120} unit="min"
          onChange={(v) => set('collision_timeout_minutes', v)}
        />

        <NumberField
          label="Conversation idle timeout"
          hint="Auto-resolve a ticket after this long with no reply from the reporter."
          value={cfg.conversation_idle_timeout_hours}
          min={1} max={168} unit="hr"
          onChange={(v) => set('conversation_idle_timeout_hours', v)}
        />
      </div>

      {/* Info note */}
      <div className="flex gap-2.5 rounded-lg bg-blue-50 dark:bg-blue-900/20
                      border border-blue-200 dark:border-blue-800 px-3.5 py-3">
        <Info className="h-4 w-4 text-blue-500 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700 dark:text-blue-300">
          All thresholds can be adjusted live from Admin → Agent Config without restarting AURA.
        </p>
      </div>
    </div>
  )
}
