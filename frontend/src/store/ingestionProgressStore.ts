import { create } from 'zustand'

export interface IngestionProgressEvent {
  run_id:            string
  status:            'started' | 'fetched' | 'processing' | 'completed' | 'failed'
  progress_pct:      number
  tickets_fetched:   number
  tickets_processed: number
  tickets_indexed:   number
  tickets_skipped:   number
  chunks_created:    number
  message:           string
}

interface IngestionProgressState {
  latest:    IngestionProgressEvent | null
  setLatest: (event: IngestionProgressEvent) => void
}

// Holds the most recent INGESTION_PROGRESS/INGESTION_COMPLETE WebSocket
// event so any page watching a run (Setup Wizard, Admin > Knowledge Index)
// can show a live "X/Y tickets" counter without opening its own connection.
export const useIngestionProgressStore = create<IngestionProgressState>((set) => ({
  latest: null,
  setLatest: (event) => set({ latest: event }),
}))
