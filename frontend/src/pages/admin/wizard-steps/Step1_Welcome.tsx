import { useEffect } from 'react'
import { Zap, ShieldCheck, Brain, ArrowRight } from 'lucide-react'

interface Step1Data {
  acknowledged: boolean
}

interface Props {
  initialData?: Partial<Step1Data>
  onChange: (data: Step1Data, valid: boolean) => void
}

const FEATURES = [
  {
    icon: Brain,
    title: 'RAG-grounded resolution',
    desc:  'AURA retrieves knowledge from your resolved ticket history and posts grounded answers to new tickets.',
  },
  {
    icon: ShieldCheck,
    title: 'Confidence-gated posting',
    desc:  'Auto-posts only at ≥90% confidence. Lower scores are held for your technicians to review.',
  },
  {
    icon: Zap,
    title: 'Real-time notifications',
    desc:  'WebSocket events keep your team informed the moment AURA acts or flags a ticket.',
  },
]

export default function Step1_Welcome({ onChange }: Props) {
  useEffect(() => {
    onChange({ acknowledged: true }, true)
  }, [onChange])

  return (
    <div className="space-y-5">
      {/* Heading */}
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Welcome to AURA
        </h2>
        <p className="mt-1.5 text-sm text-body">
          This wizard takes about 5 minutes. You can save progress and return at any time.
        </p>
      </div>

      {/* Feature cards */}
      <div className="grid gap-3">
        {FEATURES.map(({ icon: Icon, title, desc }) => (
          <div key={title} className="card p-4 flex gap-4">
            <Icon className="h-4.5 w-4.5 text-faint flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-ink">{title}</p>
              <p className="mt-0.5 text-xs text-faint leading-relaxed">{desc}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Steps overview */}
      <div className="card p-4">
        <h3 className="overline-label mb-3">
          What we'll configure
        </h3>
        <ul className="space-y-2">
          {[
            'Your ITSM platform (Jira or Zendesk) & workspace connection',
            'Ticket categories & SLA targets',
            'Team members & roles',
            'Agent confidence thresholds',
            'Initial knowledge base ingestion',
          ].map((item, i) => (
            <li key={i} className="flex items-center gap-2.5 text-sm text-body">
              <ArrowRight className="h-3.5 w-3.5 text-faint flex-shrink-0" />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
