import { useState, useEffect, useCallback } from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/utils/cn'
import type { ItsmProvider } from '@/utils/constants'

export type { ItsmProvider }

export interface Step2ProviderData {
  itsm_provider: ItsmProvider
}

interface Props {
  initialData?: Partial<Step2ProviderData>
  onChange: (data: Step2ProviderData, valid: boolean) => void
}

const PROVIDERS: { id: ItsmProvider; name: string; desc: string }[] = [
  {
    id:   'jira',
    name: 'Jira Service Management',
    desc: 'Connect AURA to a JSM cloud workspace via its REST API.',
  },
  {
    id:   'zendesk',
    name: 'Zendesk',
    desc: 'Connect AURA to a Zendesk subdomain via its REST API.',
  },
]

export default function Step2_ChooseProvider({ initialData, onChange }: Props) {
  const [selected, setSelected] = useState<ItsmProvider | null>(initialData?.itsm_provider ?? null)

  const notify = useCallback((provider: ItsmProvider | null) => {
    if (provider) onChange({ itsm_provider: provider }, true)
  }, [onChange])

  // Notify parent on mount if a prior selection exists
  useEffect(() => {
    notify(selected)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSelect = (provider: ItsmProvider) => {
    setSelected(provider)
    notify(provider)
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Choose your ITSM platform
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Select which ticketing system AURA should connect to. You'll enter connection details on the next step.
        </p>
      </div>

      <div className="grid gap-3">
        {PROVIDERS.map(({ id, name, desc }) => {
          const active = selected === id
          return (
            <button
              key={id}
              type="button"
              onClick={() => handleSelect(id)}
              className={cn(
                'card p-4 flex items-start gap-4 text-left transition-colors',
                active ? 'border-accent ring-1 ring-accent' : 'hover:border-accent/40',
              )}
            >
              <div
                className={cn(
                  'h-5 w-5 rounded-full flex-shrink-0 flex items-center justify-center border mt-0.5',
                  active ? 'bg-accent border-accent text-accent-fg' : 'border-line',
                )}
              >
                {active && <Check className="h-3 w-3" />}
              </div>
              <div>
                <p className="text-sm font-medium text-ink">{name}</p>
                <p className="mt-0.5 text-xs text-faint leading-relaxed">{desc}</p>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
