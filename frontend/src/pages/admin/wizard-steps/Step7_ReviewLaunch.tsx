import { useEffect, useCallback } from 'react'
import {
  CheckCircle2, Globe, Tag, Users, Sliders, Database, Rocket,
} from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import type { Step2ProviderData }  from './Step2_ChooseProvider'
import type { Step2Data }  from './Step2_JSMConnection'
import type { Step4ZendeskData }  from './Step4_ZendeskConnection'
import type { Step3Data }  from './Step3_CategoriesSLA'
import type { Step4Data }  from './Step4_TeamsUsers'
import type { Step5Data }  from './Step5_AgentConfig'
import type { Step6Data }  from './Step6_KnowledgeIngestion'

interface AllStepData {
  step2?: Partial<Step2Data>
  step3?: Partial<Step3Data>
  step4?: Partial<Step4Data>
  step5?: Partial<Step5Data>
  step6?: Partial<Step6Data>
}

interface Props {
  savedSteps: Record<number, unknown>
  onChange: (data: Record<string, unknown>, valid: boolean) => void
}

interface SectionProps {
  icon:     React.ElementType
  title:    string
  children: React.ReactNode
}

function Section({ icon: Icon, title, children }: SectionProps) {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-faint" />
        <h3 className="overline-label">{title}</h3>
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string | number | undefined; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between text-sm">
      <span className="text-body">{label}</span>
      <span className={`font-medium text-ink text-right max-w-[60%] truncate ${mono ? 'font-mono tabular-nums' : ''}`}>
        {value ?? '—'}
      </span>
    </div>
  )
}

export default function Step7_ReviewLaunch({ savedSteps, onChange }: Props) {
  const data = savedSteps as AllStepData & Record<string, unknown>
  // Step numbering: 1=Welcome, 2=Provider choice, 3=Branding (not shown here), 4=Connection (Jira/Zendesk),
  // 5=Model & AI Config (not shown here), 6=Categories, 7=Teams, 8=AgentConfig, 9=Knowledge, 10=Review (this step)
  const provider = ((data[2] as Partial<Step2ProviderData> | undefined)?.itsm_provider ?? 'jira')
  const isZendesk = provider === 'zendesk'
  const s2 = (data[4] ?? data.step2 ?? {}) as Partial<Step2Data>              // JSM connection is step 4
  const s2z = (data[4] ?? {}) as Partial<Step4ZendeskData>                    // Zendesk connection is step 4
  const s3 = (data[6] ?? data.step3 ?? {}) as Partial<Step3Data>              // Categories now step 6
  const s4 = (data[7] ?? data.step4 ?? {}) as Partial<Step4Data>              // Teams now step 7
  const s5 = (data[8] ?? data.step5 ?? {}) as Partial<Step5Data>              // AgentConfig now step 8
  const s6 = (data[9] ?? data.step6 ?? {}) as Partial<Step6Data>              // Knowledge now step 9

  const notify = useCallback(() => onChange({}, true), [onChange])
  useEffect(() => { notify() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const fmt = (n?: number) => n !== undefined ? `${(n * 100).toFixed(0)}%` : '—'

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Review & Launch
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Everything looks good. Review your configuration and click Launch AURA.
        </p>
      </div>

      {/* All green banner */}
      <div className="spine-agent flex items-center gap-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-900/20
                      border border-emerald-200 dark:border-emerald-800 px-4 py-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
        <span className="text-sm text-emerald-700 dark:text-emerald-300 font-medium">
          All steps completed — ready to launch
        </span>
      </div>

      {/* Connection */}
      {isZendesk ? (
        <Section icon={Globe} title="Zendesk Connection">
          <Row label="Subdomain" value={s2z.subdomain} mono />
          <Row label="Account"   value={s2z.api_email} />
          <Row label="Tickets available" mono value={
            s2z.ticket_count !== undefined ? s2z.ticket_count.toLocaleString() : '—'
          } />
        </Section>
      ) : (
        <Section icon={Globe} title="Jira Connection">
          <Row label="Workspace" value={s2.base_url} mono />
          <Row label="Project"   value={s2.project_key} mono />
          <Row label="Account"   value={s2.user_email} />
          <Row label="Tickets available" mono value={
            s2.ticket_count !== undefined ? s2.ticket_count.toLocaleString() : '—'
          } />
        </Section>
      )}

      {/* Categories */}
      <Section icon={Tag} title="Categories">
        {s3.categories?.length ? (
          <div className="divide-y divide-line">
            {s3.categories.map((c) => (
              <div key={c.id} className="flex items-center justify-between py-1.5 text-sm">
                <span className="text-body">{c.name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-faint text-xs font-mono tabular-nums">
                    {c.sla_minutes}m SLA
                  </span>
                  <Badge tone={c.auto_comment_enabled ? 'success' : 'neutral'}>
                    {c.auto_comment_enabled ? 'Auto' : 'Manual'}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-faint">No categories configured</p>
        )}
      </Section>

      {/* Users */}
      <Section icon={Users} title="Team Members">
        {s4.users?.length ? (
          <div className="divide-y divide-line">
            {s4.users.map((u) => (
              <div key={u.id} className="flex items-center justify-between py-1.5 text-sm">
                <span className="text-body">{u.display_name || u.email}</span>
                <span className="text-xs text-faint capitalize">{u.role}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-faint">No users added — add from Admin → Users after launch</p>
        )}
      </Section>

      {/* Agent config */}
      <Section icon={Sliders} title="Agent Configuration">
        <Row label="Auto-post threshold"   value={fmt(s5.confidence_threshold)}  mono />
        <Row label="Abstention threshold"  value={fmt(s5.abstention_threshold)}  mono />
        <Row label="Polling interval"      mono value={s5.polling_interval_minutes  !== undefined ? `${s5.polling_interval_minutes} min`  : '—'} />
        <Row label="Collision timeout"     mono value={s5.collision_timeout_minutes !== undefined ? `${s5.collision_timeout_minutes} min` : '—'} />
        <Row label="Conversation idle timeout" mono value={s5.conversation_idle_timeout_hours !== undefined ? `${s5.conversation_idle_timeout_hours} hr` : '—'} />
      </Section>

      {/* Knowledge base */}
      <Section icon={Database} title="Knowledge Base">
        <Row
          label="Status"
          value={
            s6.skipped            ? 'Skipped — trigger manually'
            : s6.ingestion_complete ? 'Indexed'
            : 'Not started'
          }
        />
      </Section>

      {/* Launch hint */}
      <div className="flex items-start gap-2.5 rounded-lg bg-accent-subtle
                      border border-accent/20 px-4 py-3">
        <Rocket className="h-4 w-4 text-accent mt-0.5 flex-shrink-0" />
        <p className="text-xs text-body">
          Clicking <strong>Launch AURA</strong> will apply all configuration, create the specified users,
          and start the {isZendesk ? 'Zendesk' : 'Jira'} polling scheduler. The admin dashboard will load immediately.
        </p>
      </div>
    </div>
  )
}
