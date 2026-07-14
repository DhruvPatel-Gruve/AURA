import { useState } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { Globe, Brain, Pencil, X, AlertTriangle, RefreshCw } from 'lucide-react'
import { adminApi } from '@/api/admin.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { Badge } from '@/components/ui/Badge'
import Step4_JSMConnection from './wizard-steps/Step2_JSMConnection'
import Step4_ZendeskConnection from './wizard-steps/Step4_ZendeskConnection'
import Step5_ModelAIConfig from './wizard-steps/Step5_ModelAIConfig'

function Row({ label, value, mono }: { label: string; value: string | number | null | undefined; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between text-sm">
      <span className="text-body">{label}</span>
      <span className={`font-medium text-ink text-right max-w-[60%] truncate ${mono ? 'font-mono tabular-nums' : ''}`}>
        {value ?? '—'}
      </span>
    </div>
  )
}

export default function Integrations() {
  const qc = useQueryClient()
  const [editingConnection, setEditingConnection] = useState(false)
  const [editingAI, setEditingAI] = useState(false)
  const [rebuildPrompt, setRebuildPrompt] = useState<string | null>(null)

  const { data: config, isLoading } = useQuery({
    queryKey: ['admin', 'config'],
    queryFn:  adminApi.getConfig,
  })

  const rebuildMutation = useMutation({
    mutationFn: adminApi.rebuildIndex,
    onSuccess: () => setRebuildPrompt(null),
  })

  const handleConnectionTested = () => {
    qc.invalidateQueries({ queryKey: ['admin', 'config'] })
    setEditingConnection(false)
  }

  const handleAIConfigTested = () => {
    const prevProvider = config?.embedding_provider
    const prevVectorSize = config?.embedding_vector_size
    qc.invalidateQueries({ queryKey: ['admin', 'config'] }).then(() => {
      const next = qc.getQueryData<typeof config>(['admin', 'config'])
      if (next && (next.embedding_provider !== prevProvider || next.embedding_vector_size !== prevVectorSize)) {
        setRebuildPrompt(
          'Your embedding provider or dimension changed. Existing knowledge base vectors were '
          + 'built with the previous configuration and must be rebuilt to stay searchable.',
        )
      }
    })
    setEditingAI(false)
  }

  if (isLoading || !config) {
    return (
      <div className="flex items-center justify-center p-12">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Integrations"
        description="Manage this organization's ITSM connection and AI provider configuration"
      />

      {rebuildPrompt && (
        <div className="flex items-start gap-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
          <div className="flex-1 space-y-2">
            <p className="text-sm text-amber-800 dark:text-amber-300">{rebuildPrompt}</p>
            <button
              type="button"
              onClick={() => rebuildMutation.mutate()}
              disabled={rebuildMutation.isPending}
              className="btn-secondary text-xs"
            >
              {rebuildMutation.isPending ? (
                <LoadingSpinner size="sm" />
              ) : (
                <>
                  <RefreshCw className="h-3.5 w-3.5" />
                  Rebuild knowledge base index
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── ITSM Connection ─────────────────────────────────────────────────── */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-faint" />
            <h2 className="overline-label">ITSM Connection</h2>
          </div>
          {!editingConnection && (
            <button type="button" onClick={() => setEditingConnection(true)} className="btn-secondary text-xs">
              <Pencil className="h-3.5 w-3.5" />
              Change Connection
            </button>
          )}
        </div>

        {editingConnection ? (
          <div className="space-y-3">
            {config.itsm_provider === 'zendesk' ? (
              <Step4_ZendeskConnection onChange={(_, valid) => valid && handleConnectionTested()} />
            ) : (
              <Step4_JSMConnection onChange={(_, valid) => valid && handleConnectionTested()} />
            )}
            <button type="button" onClick={() => setEditingConnection(false)} className="btn-ghost text-xs">
              <X className="h-3.5 w-3.5" />
              Cancel
            </button>
          </div>
        ) : (
          <div className="space-y-1.5">
            <Row label="Provider" value={config.itsm_provider === 'zendesk' ? 'Zendesk' : 'Jira Service Management'} />
            {config.itsm_provider === 'zendesk' ? (
              <Row label="Subdomain" value={config.zen_subdomain} mono />
            ) : (
              <>
                <Row label="Workspace" value={config.jsm_base_url} mono />
                <Row label="Project" value={config.jsm_project_key} mono />
              </>
            )}
          </div>
        )}
      </div>

      {/* ── AI Configuration ─────────────────────────────────────────────────── */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-faint" />
            <h2 className="overline-label">AI Configuration</h2>
          </div>
          {!editingAI && (
            <button type="button" onClick={() => setEditingAI(true)} className="btn-secondary text-xs">
              <Pencil className="h-3.5 w-3.5" />
              Change AI Configuration
            </button>
          )}
        </div>

        {editingAI ? (
          <div className="space-y-3">
            <p className="text-xs text-faint">
              Re-enter your API key(s) to test and save changes — for security, a previously
              saved key is never sent back to the browser and can't be reused without re-entry.
            </p>
            <Step5_ModelAIConfig onChange={(_, valid) => valid && handleAIConfigTested()} />
            <button type="button" onClick={() => setEditingAI(false)} className="btn-ghost text-xs">
              <X className="h-3.5 w-3.5" />
              Cancel
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <span className="text-body">Embeddings</span>
                <Badge tone={config.embedding_configured ? 'success' : 'warn'} dot>
                  {config.embedding_configured ? 'Configured' : 'Not configured'}
                </Badge>
              </div>
              {config.embedding_configured && (
                <>
                  <Row label="Provider" value={config.embedding_provider === 'gemini' ? 'Google Gemini' : 'OpenAI-compatible'} />
                  {config.embedding_provider === 'openai_compatible' && (
                    <Row label="Endpoint" value={config.embedding_base_url} mono />
                  )}
                  <Row label="Model" value={config.embedding_model} mono />
                  <Row label="Dimension" value={config.embedding_vector_size} mono />
                </>
              )}
            </div>
            <div className="space-y-1.5 pt-2 border-t border-line">
              <div className="flex items-center justify-between text-sm">
                <span className="text-body">LLM</span>
                <Badge tone={config.llm_configured ? 'success' : 'warn'} dot>
                  {config.llm_configured ? 'Configured' : 'Not configured'}
                </Badge>
              </div>
              {config.llm_configured && (
                <>
                  <Row label="Endpoint" value={config.llm_base_url} mono />
                  <Row label="Model" value={config.llm_model} mono />
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
