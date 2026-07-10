import { useRef, useState } from 'react'
import { CheckCircle2, FileText, Loader2, UploadCloud, XCircle } from 'lucide-react'
import { ingestionApi } from '@/api/ingestion.api'
import { cn } from '@/utils/cn'

type FileStatus = 'pending' | 'uploading' | 'done' | 'error'

interface QueuedFile {
  id:       string
  file:     File
  status:   FileStatus
  message?: string
}

interface Props {
  title?:       string
  description?: string
  onUploaded?:  () => void
  className?:   string
}

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.xlsx', '.txt', '.md', '.html', '.htm', '.csv', '.json']
const ACCEPTED = ALLOWED_EXTENSIONS.join(',')

function extensionOf(filename: string): string {
  const idx = filename.lastIndexOf('.')
  return idx === -1 ? '' : filename.slice(idx).toLowerCase()
}

export function DocumentUploadCard({ title, description, onUploaded, className }: Props) {
  const [queue, setQueue]       = useState<QueuedFile[]>([])
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const enqueue = (file: File, rejection?: string) => {
    const item: QueuedFile = {
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
      file,
      status: rejection ? 'error' : 'pending',
      message: rejection,
    }
    setQueue((prev) => [...prev, item])
    if (!rejection) upload(item)
  }

  const addFiles = (files: FileList | File[]) => {
    // Each file is validated independently — one bad file in a multi-select never blocks the rest.
    Array.from(files).forEach((file) => {
      const ext = extensionOf(file.name)
      if (!ext || !ALLOWED_EXTENSIONS.includes(ext)) {
        enqueue(file, `Unsupported file type${ext ? ` "${ext}"` : ''} — skipped`)
        return
      }
      enqueue(file)
    })
  }

  // Walks dropped entries so a dropped *folder* is rejected outright instead of
  // being silently expanded into whatever files/archives it contains.
  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)

    const items = e.dataTransfer.items
    if (items && items.length > 0 && 'webkitGetAsEntry' in items[0]) {
      const validFiles: File[] = []
      let sawDirectory = false

      for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry?.()
        if (entry?.isDirectory) {
          sawDirectory = true
          continue
        }
        const file = items[i].getAsFile()
        if (file) validFiles.push(file)
      }

      if (sawDirectory) {
        enqueue(
          new File([], 'folder'),
          'Folders can’t be uploaded directly — please select individual document files.',
        )
      }
      if (validFiles.length > 0) addFiles(validFiles)
      return
    }

    addFiles(e.dataTransfer.files)
  }

  const upload = async (item: QueuedFile) => {
    setQueue((prev) => prev.map((q) => (q.id === item.id ? { ...q, status: 'uploading' } : q)))
    try {
      const res = await ingestionApi.uploadDocument(item.file)
      setQueue((prev) =>
        prev.map((q) =>
          q.id === item.id
            ? { ...q, status: 'done', message: `${res.chunks_created} chunks indexed` }
            : q,
        ),
      )
      onUploaded?.()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Upload failed'
      setQueue((prev) => prev.map((q) => (q.id === item.id ? { ...q, status: 'error', message: msg } : q)))
    }
  }

  const clearFinished = () => setQueue((prev) => prev.filter((q) => q.status === 'uploading' || q.status === 'pending'))

  return (
    <div className={cn('card p-6 space-y-4', className)}>
      {(title || description) && (
        <div>
          {title && <h2 className="overline-label">{title}</h2>}
          {description && (
            <p className="mt-1 text-xs text-body">{description}</p>
          )}
        </div>
      )}

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          'flex flex-col items-center gap-2 rounded-lg border-2 border-dashed py-8 px-4 cursor-pointer transition-colors',
          dragOver
            ? 'border-accent bg-accent-subtle'
            : 'border-line hover:border-faint/40',
        )}
      >
        <UploadCloud className="h-7 w-7 text-faint" />
        <p className="text-sm text-body">
          <span className="font-medium text-accent">Click to upload</span> or drag and drop
        </p>
        <p className="text-xs text-faint">
          Select multiple files at once &middot; PDF, DOCX, PPTX, XLSX, TXT, MD, HTML, CSV, JSON
        </p>
        <p className="text-xs text-faint">Archives (.zip) and folders are not supported</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }}
        />
      </div>

      {queue.length > 0 && (
        <div className="space-y-2">
          {queue.map((item) => (
            <div
              key={item.id}
              className={cn(
                'flex items-center gap-3 rounded-lg border border-line px-3 py-2',
                item.status === 'done' && 'spine-agent',
                item.status === 'error' && 'spine-critical',
                item.status === 'uploading' && 'spine-active',
              )}
            >
              <FileText className="h-4 w-4 text-faint shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-ink">{item.file.name}</p>
                {item.message && (
                  <p className={cn('text-xs', item.status === 'error' ? 'text-red-600 dark:text-red-400' : 'text-faint')}>
                    {item.message}
                  </p>
                )}
              </div>
              {item.status === 'uploading' && <Loader2 className="h-4 w-4 text-accent animate-spin shrink-0" />}
              {item.status === 'done' && <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />}
              {item.status === 'error' && <XCircle className="h-4 w-4 text-red-500 shrink-0" />}
            </div>
          ))}
          {queue.some((q) => q.status === 'done' || q.status === 'error') && (
            <button type="button" onClick={clearFinished} className="btn-ghost text-xs">
              Clear finished
            </button>
          )}
        </div>
      )}
    </div>
  )
}
