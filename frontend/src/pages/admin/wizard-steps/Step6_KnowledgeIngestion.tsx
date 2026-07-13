import { useState, useEffect, useCallback, useRef } from 'react'
import { CheckCircle2, XCircle, Loader2, Database, SkipForward } from 'lucide-react'
import { ingestionApi } from '@/api/ingestion.api'
import { DocumentUploadCard } from '@/components/knowledge/DocumentUploadCard'
import { ITSM_PROVIDER_SHORT_LABELS, type ItsmProvider } from '@/utils/constants'
import { useIngestionProgressStore } from '@/store/ingestionProgressStore'

export interface Step6Data {
  ingestion_triggered: boolean
  ingestion_complete:  boolean
  skipped:             boolean
  run_id?:             string
}

interface Props {
  initialData?: Partial<Step6Data>
  provider?: ItsmProvider
  onChange: (data: Step6Data, valid: boolean) => void
}

type Phase = 'idle' | 'running' | 'done' | 'error' | 'skipped'

export default function Step6_KnowledgeIngestion({ initialData, provider = 'jira', onChange }: Props) {
  const providerLabel = ITSM_PROVIDER_SHORT_LABELS[provider]
  const initPhase = (): Phase => {
    if (initialData?.skipped)            return 'skipped'
    if (initialData?.ingestion_complete) return 'done'
    if (initialData?.ingestion_triggered) return 'running'
    return 'idle'
  }

  const [phase,          setPhase]          = useState<Phase>(initPhase)
  const [runId,          setRunId]          = useState<string | undefined>(initialData?.run_id)
  const [progress,       setProgress]       = useState<number>(0)
  const [ticketProgress, setTicketProgress] = useState<{ processed: number; total: number } | null>(null)
  const [errMsg,         setErrMsg]         = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const latestIngestionEvent = useIngestionProgressStore((s) => s.latest)

  const buildData = useCallback((p: Phase, rid?: string): Step6Data => ({
    ingestion_triggered: p !== 'idle',
    ingestion_complete:  p === 'done',
    skipped:             p === 'skipped',
    run_id:              rid,
  }), [])

  const notify = useCallback(
    (p: Phase, rid?: string) => {
      const valid = p === 'done' || p === 'skipped'
      onChange(buildData(p, rid), valid)
    },
    [onChange, buildData],
  )

  // Restore running state on mount
  useEffect(() => {
    if (phase === 'running') startPolling()
    else notify(phase, runId)
    return () => stopPolling()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Live per-ticket counter — driven by the INGESTION_PROGRESS/COMPLETE
  // WebSocket events pushed while this run is active. Polling (below) stays
  // as the source of truth for phase transitions in case a message is
  // missed; this just makes the "X/Y tickets" count update immediately.
  useEffect(() => {
    if (!latestIngestionEvent || phase !== 'running' || latestIngestionEvent.run_id !== runId) return

    setProgress(latestIngestionEvent.progress_pct)
    setTicketProgress({
      processed: latestIngestionEvent.tickets_processed,
      total: latestIngestionEvent.tickets_fetched,
    })

    if (latestIngestionEvent.status === 'completed') {
      stopPolling()
      setPhase('done')
      notify('done', runId)
    } else if (latestIngestionEvent.status === 'failed') {
      stopPolling()
      setPhase('error')
      setErrMsg('Ingestion failed. You can skip and retry later from Admin → Knowledge Index.')
      notify('error', runId)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestIngestionEvent])

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startPolling = () => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const status = await ingestionApi.getStatus()
        if (status.progress !== undefined) setProgress(Math.round(status.progress * 100))
        if (status.status === 'completed') {
          stopPolling()
          setPhase('done')
          notify('done', status.run_id ?? runId)
        } else if (status.status === 'failed') {
          stopPolling()
          setPhase('error')
          setErrMsg('Ingestion failed. You can skip and retry later from Admin → Knowledge Index.')
          notify('error', status.run_id ?? runId)
        }
      } catch { /* ignore transient errors, keep polling */ }
    }, 3000)
  }

  const handleStart = async () => {
    setErrMsg(null)
    setPhase('running')
    setProgress(0)
    setTicketProgress(null)
    try {
      const res = await ingestionApi.trigger()
      setRunId(res.run_id)
      notify('running', res.run_id)
      startPolling()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Failed to start ingestion'
      setErrMsg(msg)
      setPhase('error')
      notify('error')
    }
  }

  const handleSkip = () => {
    stopPolling()
    setPhase('skipped')
    notify('skipped')
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink">
          Knowledge Base
        </h2>
        <p className="mt-1.5 text-sm text-body">
          Ingest your resolved {providerLabel} tickets to build the RAG knowledge base. AURA needs this to generate answers.
        </p>
      </div>

      <div className="card p-6">
        {phase === 'idle' && (
          <div className="flex flex-col items-center gap-4 py-4">
            <Database className="h-8 w-8 text-faint" />
            <div className="text-center">
              <p className="text-sm font-medium text-ink">Ready to index</p>
              <p className="text-xs text-faint mt-1 max-w-xs">
                AURA will fetch all resolved tickets from your {providerLabel} project, chunk and embed them.
                This may take a few minutes depending on ticket volume.
              </p>
            </div>
            <div className="flex gap-3">
              <button type="button" onClick={handleSkip} className="btn-ghost gap-1.5">
                <SkipForward className="h-3.5 w-3.5" />
                Skip for now
              </button>
              <button type="button" onClick={handleStart} className="btn-primary">
                Start ingestion
              </button>
            </div>
          </div>
        )}

        {phase === 'running' && (
          <div className="flex flex-col items-center gap-4 py-4">
            <Loader2 className="h-8 w-8 text-accent animate-spin" />
            <div className="text-center">
              <p className="text-sm font-medium text-ink">Indexing tickets…</p>
              <p className="text-xs text-faint mt-1">
                Fetching → chunking → embedding → storing in Qdrant
              </p>
            </div>
            {/* Progress bar */}
            <div className="w-full max-w-xs">
              <div className="h-1.5 bg-sunken rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent rounded-full transition-all duration-500"
                  style={{ width: `${progress || 5}%` }}
                />
              </div>
              <p className="text-xs font-mono text-faint mt-1.5 text-center tabular-nums">
                {ticketProgress
                  ? `${ticketProgress.processed} / ${ticketProgress.total} tickets processed`
                  : progress > 0 ? `${progress}%` : 'Starting…'}
              </p>
            </div>
            <button type="button" onClick={handleSkip} className="btn-ghost text-xs">
              Skip and continue
            </button>
          </div>
        )}

        {phase === 'done' && (
          <div className="flex flex-col items-center gap-3 py-4">
            <CheckCircle2 className="h-10 w-10 text-emerald-500" />
            <div className="text-center">
              <p className="text-sm font-medium text-ink">Indexing complete</p>
              <p className="text-xs text-faint mt-1">
                Knowledge base is ready. AURA can now generate grounded answers.
              </p>
            </div>
          </div>
        )}

        {(phase === 'error') && (
          <div className="flex flex-col items-center gap-3 py-4">
            <XCircle className="h-10 w-10 text-red-500" />
            <div className="text-center">
              <p className="text-sm font-medium text-ink">Ingestion failed</p>
              {errMsg && (
                <p className="text-xs text-red-500 dark:text-red-400 mt-1">{errMsg}</p>
              )}
            </div>
            <div className="flex gap-3">
              <button type="button" onClick={handleSkip} className="btn-ghost gap-1.5">
                <SkipForward className="h-3.5 w-3.5" />
                Skip for now
              </button>
              <button type="button" onClick={handleStart} className="btn-primary">
                Retry
              </button>
            </div>
          </div>
        )}

        {phase === 'skipped' && (
          <div className="flex flex-col items-center gap-3 py-4">
            <div className="h-10 w-10 rounded-full flex items-center justify-center bg-sunken">
              <SkipForward className="h-5 w-5 text-faint" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-ink">Skipped</p>
              <p className="text-xs text-faint mt-1">
                Trigger ingestion after setup from Admin → Knowledge Index.
              </p>
            </div>
            <button type="button" onClick={() => { setPhase('idle'); notify('idle') }} className="btn-ghost text-xs">
              Start ingestion instead
            </button>
          </div>
        )}
      </div>

      <DocumentUploadCard
        title="Upload Documents"
        description={`Add runbooks, policies, or manuals (PDF, DOCX, PPTX, XLSX, TXT, MD, HTML) to the RAG knowledge base alongside your ${providerLabel} tickets. Optional — you can also do this later from Admin → Knowledge Index.`}
      />
    </div>
  )
}
