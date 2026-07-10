import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Cpu, Ticket, AlertTriangle, FileText, Trash2, Search } from 'lucide-react'
import type { DocumentSummary } from '@/api/types'
import { adminApi } from '@/api/admin.api'
import { ingestionApi } from '@/api/ingestion.api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatCard } from '@/components/ui/StatCard'
import { Modal } from '@/components/ui/Modal'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { DocumentUploadCard } from '@/components/knowledge/DocumentUploadCard'
import { formatRelativeTime } from '@/utils/formatters'

interface QdrantStats {
  documents_count:       number
  tickets_count:         number
  total_chunks:          number
  last_sync:             string | null
  coverage_by_category:  Array<{ category: string; count: number; pct: number }>
}

export default function QdrantIndex() {
  const qc = useQueryClient()
  const [rebuildOpen, setRebuildOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ doc_id: string; filename: string } | null>(null)

  const { data: stats, isLoading } = useQuery({
    queryKey: ['admin', 'qdrant', 'stats'],
    queryFn:  async () => {
      const d = await adminApi.getQdrantStats()
      return d as unknown as QdrantStats
    },
    refetchInterval: 30_000,
  })

  const { data: documents, isLoading: docsLoading } = useQuery({
    queryKey: ['admin', 'documents'],
    queryFn:  adminApi.getDocuments,
  })

  const [docSearch, setDocSearch] = useState('')
  const [docSort, setDocSort]     = useState<'name' | 'chunks' | 'uploaded'>('uploaded')

  const visibleDocuments: DocumentSummary[] = (documents ?? [])
    .filter((d) => d.filename.toLowerCase().includes(docSearch.trim().toLowerCase()))
    .sort((a, b) => {
      if (docSort === 'name') return a.filename.localeCompare(b.filename)
      if (docSort === 'chunks') return b.chunk_count - a.chunk_count
      return (b.uploaded_at ?? '').localeCompare(a.uploaded_at ?? '')
    })

  const triggerMutation = useMutation({
    mutationFn: ingestionApi.trigger,
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['admin', 'qdrant', 'stats'] }),
  })

  const rebuildMutation = useMutation({
    mutationFn: adminApi.rebuildIndex,
    onSuccess:  () => {
      qc.invalidateQueries({ queryKey: ['admin', 'qdrant', 'stats'] })
      qc.invalidateQueries({ queryKey: ['admin', 'documents'] })
      setRebuildOpen(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (docId: string) => adminApi.deleteDocument(docId),
    onSuccess:  () => {
      qc.invalidateQueries({ queryKey: ['admin', 'documents'] })
      qc.invalidateQueries({ queryKey: ['admin', 'qdrant', 'stats'] })
      setDeleteTarget(null)
    },
  })

  const refreshKnowledgeBase = () => {
    qc.invalidateQueries({ queryKey: ['admin', 'documents'] })
    qc.invalidateQueries({ queryKey: ['admin', 'qdrant', 'stats'] })
  }

  // Backend returns coverage_by_category as { [category]: count } dict; normalise to array
  const rawCoverage = stats?.coverage_by_category
  const coverage: Array<{ category: string; count: number; pct: number }> = Array.isArray(rawCoverage)
    ? rawCoverage
    : rawCoverage && typeof rawCoverage === 'object'
      ? Object.entries(rawCoverage as Record<string, number>).map(([category, count]) => ({
          category,
          count,
          pct: (stats?.total_chunks ?? 0) > 0 ? (count / stats!.total_chunks) * 100 : 0,
        }))
      : []
  const maxCount = Math.max(...coverage.map((c) => c.count), 1)

  return (
    <div className="space-y-5">
      <PageHeader
        title="Knowledge Index"
        description="Qdrant vector database statistics and management"
        actions={
          <>
            <button
              onClick={() => triggerMutation.mutate()}
              disabled={triggerMutation.isPending}
              className="btn-secondary"
            >
              {triggerMutation.isPending
                ? <LoadingSpinner size="sm" />
                : <RefreshCw className="h-4 w-4" />
              }
              Re-ingest
            </button>
            <button
              onClick={() => setRebuildOpen(true)}
              className="btn-danger"
            >
              <Cpu className="h-4 w-4" />
              Rebuild Index
            </button>
          </>
        }
      />

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Documents Ingested"
          value={isLoading ? '—' : (stats?.documents_count ?? 0).toLocaleString()}
          icon={FileText}
          loading={isLoading}
        />
        <StatCard
          label="Resolved Tickets Ingested"
          value={isLoading ? '—' : (stats?.tickets_count ?? 0).toLocaleString()}
          icon={Ticket}
          loading={isLoading}
        />
        <StatCard
          label="Categories Covered"
          value={isLoading ? '—' : coverage.length}
          icon={Cpu}
          loading={isLoading}
        />
        <StatCard
          label="Last Sync"
          value={stats?.last_sync ? formatRelativeTime(stats.last_sync) : 'Never'}
          loading={isLoading}
        />
      </div>

      {/* Upload documents */}
      <DocumentUploadCard
        title="Upload Documents"
        description="Add runbooks, policies, or manuals to the RAG knowledge base."
        onUploaded={refreshKnowledgeBase}
      />

      {/* Uploaded documents list */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <h2 className="overline-label">
            Uploaded Documents
          </h2>
          {documents && documents.length > 0 && (
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
                <input
                  type="text"
                  value={docSearch}
                  onChange={(e) => setDocSearch(e.target.value)}
                  placeholder="Search filename…"
                  className="input-base pl-8 w-48 text-sm"
                />
              </div>
              <select
                value={docSort}
                onChange={(e) => setDocSort(e.target.value as typeof docSort)}
                className="input-base w-36 text-sm"
              >
                <option value="uploaded">Newest first</option>
                <option value="name">Name (A-Z)</option>
                <option value="chunks">Most chunks</option>
              </select>
            </div>
          )}
        </div>
        {docsLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-10" />
            ))}
          </div>
        ) : !documents || documents.length === 0 ? (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-sunken">
            <FileText className="h-4 w-4 text-faint shrink-0" />
            <p className="text-sm text-faint">
              No documents uploaded yet. Use the uploader above to add to the knowledge base.
            </p>
          </div>
        ) : visibleDocuments.length === 0 ? (
          <p className="text-sm text-faint py-4 text-center">No documents match "{docSearch}"</p>
        ) : (
          <div className="divide-y divide-line">
            {visibleDocuments.map((doc) => (
              <div key={doc.doc_id} className="flex items-center gap-3 py-2.5">
                <FileText className="h-4 w-4 text-faint shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">{doc.filename}</p>
                  <p className="text-xs font-mono text-faint">
                    {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'}
                    {doc.uploaded_at ? ` · ${formatRelativeTime(doc.uploaded_at)}` : ''}
                  </p>
                </div>
                <button
                  onClick={() => setDeleteTarget({ doc_id: doc.doc_id, filename: doc.filename })}
                  className="btn-ghost !p-1.5 text-faint hover:text-red-500"
                  title="Delete document"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Coverage by category */}
      <div className="card p-5">
        <h2 className="overline-label mb-4">
          Coverage by Category
        </h2>
        {isLoading ? (
          <div className="space-y-3">
            {[1,2,3,4].map((i) => (
              <div key={i} className="skeleton h-8" />
            ))}
          </div>
        ) : coverage.length === 0 ? (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20">
            <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
            <p className="text-sm text-amber-700 dark:text-amber-300">
              No documents indexed yet. Run an ingestion to populate the knowledge base.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {coverage.map((c) => (
              <div key={c.category} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-body">{c.category}</span>
                  <span className="font-mono tabular-nums text-faint">
                    {c.count.toLocaleString()} docs
                  </span>
                </div>
                <ProgressBar
                  value={(c.count / maxCount) * 100}
                  size="sm"
                  color={c.pct > 10 ? 'emerald' : 'amber'}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Rebuild confirmation */}
      <Modal open={rebuildOpen} onClose={() => setRebuildOpen(false)} title="Rebuild Knowledge Index?">
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-3 rounded-lg bg-red-50 dark:bg-red-900/20">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <p className="text-sm text-red-700 dark:text-red-300">
              This will clear all vectors and re-index from scratch. The knowledge base will be
              unavailable for several minutes. AURA will abstain on all tickets during this time.
            </p>
          </div>
          {rebuildMutation.isError && (
            <p className="text-xs text-red-500">Rebuild failed. Please try again.</p>
          )}
          <div className="flex justify-end gap-2">
            <button onClick={() => setRebuildOpen(false)} className="btn-ghost">Cancel</button>
            <button
              onClick={() => rebuildMutation.mutate()}
              disabled={rebuildMutation.isPending}
              className="btn-danger"
            >
              {rebuildMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : null}
              Rebuild Index
            </button>
          </div>
        </div>
      </Modal>

      {/* Delete document confirmation */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Document?"
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-3 rounded-lg bg-red-50 dark:bg-red-900/20">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <p className="text-sm text-red-700 dark:text-red-300">
              This will remove all indexed chunks for &ldquo;{deleteTarget?.filename}&rdquo; from the
              knowledge base. AURA will no longer be able to cite this document.
            </p>
          </div>
          {deleteMutation.isError && (
            <p className="text-xs text-red-500">Delete failed. Please try again.</p>
          )}
          <div className="flex justify-end gap-2">
            <button onClick={() => setDeleteTarget(null)} className="btn-ghost">Cancel</button>
            <button
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.doc_id)}
              disabled={deleteMutation.isPending}
              className="btn-danger"
            >
              {deleteMutation.isPending ? <LoadingSpinner size="sm" className="text-white" /> : null}
              Delete
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
