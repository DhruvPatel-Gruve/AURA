import { useState, useEffect, useCallback } from 'react'
import { Loader2, Eye, EyeOff, Check } from 'lucide-react'
import { setupApi } from '@/api/setup.api'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/utils/cn'

type EmbeddingProvider = 'gemini' | 'openai_compatible'

export interface Step5Data {
  embedding_provider:      EmbeddingProvider
  embeddings_tested:       boolean
  embedding_vector_size?:  number
  llm_tested:              boolean
}

interface Props {
  initialData?: Partial<Step5Data>
  onChange: (data: Step5Data, valid: boolean) => void
}

export default function Step5_ModelAIConfig({ initialData, onChange }: Props) {
  // ── Embeddings sub-state ────────────────────────────────────────────────────
  const [embedProvider, setEmbedProvider]   = useState<EmbeddingProvider>(initialData?.embedding_provider ?? 'gemini')
  const [embedApiKey,   setEmbedApiKey]     = useState('')
  const [embedBaseUrl,  setEmbedBaseUrl]    = useState('')
  const [embedModel,    setEmbedModel]      = useState('')
  const [embedVectorSize, setEmbedVectorSize] = useState('')
  const [embedShowKey,  setEmbedShowKey]    = useState(false)
  const [embedTested,   setEmbedTested]     = useState(initialData?.embeddings_tested ?? false)
  const [embedTestedVectorSize, setEmbedTestedVectorSize] = useState<number | undefined>(initialData?.embedding_vector_size)
  const [embedTesting,  setEmbedTesting]    = useState(false)
  const [embedError,    setEmbedError]      = useState<string | null>(null)
  const [showAdvanced,  setShowAdvanced]    = useState(false)

  // ── LLM sub-state ────────────────────────────────────────────────────────────
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [llmModel,   setLlmModel]   = useState('')
  const [llmApiKey,  setLlmApiKey]  = useState('')
  const [llmShowKey, setLlmShowKey] = useState(false)
  const [llmTested,  setLlmTested]  = useState(initialData?.llm_tested ?? false)
  const [llmSampleReply, setLlmSampleReply] = useState<string | null>(null)
  const [llmTesting, setLlmTesting] = useState(false)
  const [llmError,   setLlmError]   = useState<string | null>(null)

  const notify = useCallback(
    (provider: EmbeddingProvider, eTested: boolean, lTested: boolean, vectorSize?: number) => {
      onChange(
        {
          embedding_provider:     provider,
          embeddings_tested:      eTested,
          embedding_vector_size:  vectorSize,
          llm_tested:             lTested,
        },
        eTested && lTested,
      )
    },
    [onChange],
  )

  // Notify parent on mount
  useEffect(() => {
    notify(embedProvider, embedTested, llmTested, embedTestedVectorSize)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleProviderChange = (p: EmbeddingProvider) => {
    setEmbedProvider(p)
    setEmbedTested(false)
    setEmbedError(null)
    notify(p, false, llmTested)
  }

  const handleEmbedField = (setter: (v: string) => void) => (value: string) => {
    setter(value)
    setEmbedTested(false)
    setEmbedError(null)
    notify(embedProvider, false, llmTested)
  }

  const handleLlmField = (setter: (v: string) => void) => (value: string) => {
    setter(value)
    setLlmTested(false)
    setLlmError(null)
    notify(embedProvider, embedTested, false, embedTestedVectorSize)
  }

  const handleTestEmbedding = async () => {
    setEmbedTesting(true)
    setEmbedError(null)
    try {
      const res = await setupApi.testEmbeddingConnection({
        provider: embedProvider,
        api_key:  embedApiKey.trim(),
        base_url: embedProvider === 'openai_compatible' ? embedBaseUrl.trim() : undefined,
        model:    embedModel.trim() || undefined,
        vector_size: embedProvider === 'openai_compatible' ? Number(embedVectorSize) : undefined,
      })
      if (res.success) {
        setEmbedTested(true)
        setEmbedTestedVectorSize(res.vector_size)
        notify(embedProvider, true, llmTested, res.vector_size)
      } else {
        setEmbedError(res.error ?? 'Connection failed')
        notify(embedProvider, false, llmTested)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Could not reach embedding provider'
      setEmbedError(msg)
      notify(embedProvider, false, llmTested)
    } finally {
      setEmbedTesting(false)
    }
  }

  const handleTestLlm = async () => {
    setLlmTesting(true)
    setLlmError(null)
    try {
      const res = await setupApi.testLlmConnection({
        base_url: llmBaseUrl.trim(),
        model:    llmModel.trim(),
        api_key:  llmApiKey.trim() || undefined,
      })
      if (res.success) {
        setLlmTested(true)
        setLlmSampleReply(res.sample_reply)
        notify(embedProvider, embedTested, true, embedTestedVectorSize)
      } else {
        setLlmError(res.error ?? 'Connection failed')
        notify(embedProvider, embedTested, false, embedTestedVectorSize)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Could not reach LLM endpoint'
      setLlmError(msg)
      notify(embedProvider, embedTested, false, embedTestedVectorSize)
    } finally {
      setLlmTesting(false)
    }
  }

  const embedCanTest = embedProvider === 'gemini'
    ? embedApiKey.trim() !== ''
    : embedApiKey.trim() !== '' && embedBaseUrl.trim() !== '' && embedModel.trim() !== '' && embedVectorSize.trim() !== ''
  const llmCanTest = llmBaseUrl.trim() !== '' && llmModel.trim() !== ''

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-ink">Model &amp; AI Configuration</h2>
        <p className="mt-1.5 text-sm text-body">
          Bring your own embedding and language model provider. Every organization's AI
          configuration is fully isolated — no key or endpoint is ever shared with another tenant.
        </p>
      </div>

      {/* ── Embeddings ────────────────────────────────────────────────────────── */}
      <div className="card p-5 space-y-4">
        <h3 className="text-sm font-semibold text-ink">Embeddings (knowledge base search)</h3>

        <div className="grid grid-cols-2 gap-3">
          {(['gemini', 'openai_compatible'] as const).map((p) => {
            const active = embedProvider === p
            return (
              <button
                key={p}
                type="button"
                onClick={() => handleProviderChange(p)}
                className={cn(
                  'rounded-lg border p-3 text-left transition-colors',
                  active ? 'border-accent ring-1 ring-accent' : 'border-line hover:border-accent/40',
                )}
              >
                <div className="flex items-center gap-2">
                  <div className={cn(
                    'h-4 w-4 rounded-full flex items-center justify-center border flex-shrink-0',
                    active ? 'bg-accent border-accent text-accent-fg' : 'border-line',
                  )}>
                    {active && <Check className="h-2.5 w-2.5" />}
                  </div>
                  <span className="text-sm font-medium text-ink">
                    {p === 'gemini' ? 'Google Gemini' : 'OpenAI-compatible endpoint'}
                  </span>
                </div>
              </button>
            )
          })}
        </div>

        {embedProvider === 'gemini' ? (
          <>
            <div>
              <label className="block text-sm font-medium text-body mb-1.5">Gemini API key</label>
              <div className="relative">
                <input
                  type={embedShowKey ? 'text' : 'password'}
                  value={embedApiKey}
                  onChange={(e) => handleEmbedField(setEmbedApiKey)(e.target.value)}
                  placeholder="••••••••••••••••••••"
                  className="input-base pr-10"
                />
                <button
                  type="button"
                  onClick={() => setEmbedShowKey((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-body"
                  tabIndex={-1}
                >
                  {embedShowKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="mt-1 text-xs text-faint">Generate at Google AI Studio → API keys</p>
            </div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-faint hover:text-body underline"
            >
              {showAdvanced ? 'Hide' : 'Show'} advanced options
            </button>
            {showAdvanced && (
              <div>
                <label className="block text-sm font-medium text-body mb-1.5">Model override (optional)</label>
                <input
                  type="text"
                  value={embedModel}
                  onChange={(e) => handleEmbedField(setEmbedModel)(e.target.value)}
                  placeholder="models/gemini-embedding-2"
                  className="input-base font-mono"
                />
              </div>
            )}
          </>
        ) : (
          <>
            <div>
              <label className="block text-sm font-medium text-body mb-1.5">Endpoint base URL</label>
              <input
                type="url"
                value={embedBaseUrl}
                onChange={(e) => handleEmbedField(setEmbedBaseUrl)(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className="input-base font-mono"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-body mb-1.5">API key</label>
              <div className="relative">
                <input
                  type={embedShowKey ? 'text' : 'password'}
                  value={embedApiKey}
                  onChange={(e) => handleEmbedField(setEmbedApiKey)(e.target.value)}
                  placeholder="••••••••••••••••••••"
                  className="input-base pr-10"
                />
                <button
                  type="button"
                  onClick={() => setEmbedShowKey((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-body"
                  tabIndex={-1}
                >
                  {embedShowKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-body mb-1.5">Model name</label>
              <input
                type="text"
                value={embedModel}
                onChange={(e) => handleEmbedField(setEmbedModel)(e.target.value)}
                placeholder="text-embedding-3-small"
                className="input-base font-mono"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-body mb-1.5">Embedding dimension</label>
              <input
                type="number"
                value={embedVectorSize}
                onChange={(e) => handleEmbedField(setEmbedVectorSize)(e.target.value)}
                placeholder="1536"
                className="input-base font-mono"
              />
              <p className="mt-1 text-xs text-faint">
                Check your model's docs — e.g. 1536 for text-embedding-3-small
              </p>
            </div>
          </>
        )}

        {embedTested && (
          <div className="flex items-center gap-2.5 rounded-lg bg-sunken border border-line px-3.5 py-2.5">
            <Badge tone="success" dot>Connected</Badge>
            <span className="text-sm text-body font-mono tabular-nums">
              {embedTestedVectorSize}-dim vectors
            </span>
          </div>
        )}
        {embedError && (
          <div className="flex items-start gap-2.5 rounded-lg bg-sunken border border-line px-3.5 py-2.5">
            <Badge tone="critical" dot>Failed</Badge>
            <span className="text-sm text-body font-mono">{embedError}</span>
          </div>
        )}

        <button
          type="button"
          onClick={handleTestEmbedding}
          disabled={!embedCanTest || embedTesting}
          className="btn-secondary w-full"
        >
          {embedTesting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Testing…
            </>
          ) : (
            'Test Embeddings'
          )}
        </button>
      </div>

      {/* ── LLM ───────────────────────────────────────────────────────────────── */}
      <div className="card p-5 space-y-4">
        <h3 className="text-sm font-semibold text-ink">LLM (resolution &amp; chat generation)</h3>

        <div>
          <label className="block text-sm font-medium text-body mb-1.5">Endpoint base URL</label>
          <input
            type="url"
            value={llmBaseUrl}
            onChange={(e) => handleLlmField(setLlmBaseUrl)(e.target.value)}
            placeholder="http://localhost:11434/v1"
            className="input-base font-mono"
          />
          <p className="mt-1 text-xs text-faint">
            Any OpenAI-compatible chat completions endpoint (Ollama, vLLM, OpenAI, etc.)
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-body mb-1.5">Model name</label>
          <input
            type="text"
            value={llmModel}
            onChange={(e) => handleLlmField(setLlmModel)(e.target.value)}
            placeholder="qwen3:8b"
            className="input-base font-mono"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-body mb-1.5">API key (optional)</label>
          <div className="relative">
            <input
              type={llmShowKey ? 'text' : 'password'}
              value={llmApiKey}
              onChange={(e) => handleLlmField(setLlmApiKey)(e.target.value)}
              placeholder="Leave blank if not required"
              className="input-base pr-10"
            />
            <button
              type="button"
              onClick={() => setLlmShowKey((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-body"
              tabIndex={-1}
            >
              {llmShowKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {llmTested && (
          <div className="flex items-center gap-2.5 rounded-lg bg-sunken border border-line px-3.5 py-2.5">
            <Badge tone="success" dot>Connected</Badge>
            <span className="text-sm text-body font-mono truncate">
              Model responded: "{llmSampleReply}"
            </span>
          </div>
        )}
        {llmError && (
          <div className="flex items-start gap-2.5 rounded-lg bg-sunken border border-line px-3.5 py-2.5">
            <Badge tone="critical" dot>Failed</Badge>
            <span className="text-sm text-body font-mono">{llmError}</span>
          </div>
        )}

        <button
          type="button"
          onClick={handleTestLlm}
          disabled={!llmCanTest || llmTesting}
          className="btn-secondary w-full"
        >
          {llmTesting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Testing…
            </>
          ) : (
            'Test LLM'
          )}
        </button>
      </div>

      {!(embedTested && llmTested) && (
        <p className="text-xs text-faint text-center">
          You must successfully test both embeddings and the LLM before continuing.
        </p>
      )}
    </div>
  )
}
