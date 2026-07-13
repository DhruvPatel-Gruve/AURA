import { useEffect, useRef, useCallback } from 'react'
import { useAuthStore } from '@/store/authStore'
import { useConfigStore } from '@/store/configStore'
import { useNotificationStore } from '@/store/notificationStore'
import { useToastStore } from '@/store/toastStore'
import { useIngestionProgressStore, type IngestionProgressEvent } from '@/store/ingestionProgressStore'
import { useQueryClient } from '@tanstack/react-query'
import { WS_EVENTS } from '@/utils/constants'
import type { WSEvent } from '@/api/types'

const WS_BASE = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'
const BACKOFF  = [2000, 4000, 8000, 16000, 30000]

export function useWebSocket() {
  const wsRef     = useRef<WebSocket | null>(null)
  const attemptRef = useRef(0)
  const qc        = useQueryClient()

  const { accessToken, userId, updateProfile } = useAuthStore()
  const { setKillSwitch }          = useConfigStore()
  const { push }                   = useNotificationStore()
  const showToast                  = useToastStore((s) => s.show)

  const dispatch = useCallback((evt: WSEvent) => {
    const { event_type: type, payload, timestamp } = evt

    // Dashboard stat cards otherwise only refresh on their own poll interval
    // (30-60s) even though the backend already announced the change live —
    // invalidate the shared dashboard query-key prefixes so open dashboards
    // update immediately instead of waiting for the next poll.
    const invalidateDashboards = () => {
      qc.invalidateQueries({ queryKey: ['technician'] })
      qc.invalidateQueries({ queryKey: ['manager'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    }

    switch (type) {
      case WS_EVENTS.KILL_SWITCH_ACTIVATED:
        setKillSwitch(true)
        push({ event_type: type, message: 'AURA has been suspended by admin', timestamp })
        break
      case WS_EVENTS.KILL_SWITCH_DEACTIVATED:
        setKillSwitch(false)
        push({ event_type: type, message: 'AURA has been re-enabled', timestamp })
        break
      case WS_EVENTS.TICKET_ASSIGNED: {
        const p = payload as { ticket_id?: string; technician_id?: string }
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        if (p.ticket_id) qc.invalidateQueries({ queryKey: ['tickets', p.ticket_id] })
        invalidateDashboards()
        const message = `New ticket assigned to you: ${p.ticket_id ?? ''}`
        push({ event_type: type, message, timestamp })
        if (p.technician_id === userId) showToast(message, 'info')
        break
      }
      case WS_EVENTS.TICKET_UPDATED:
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        qc.invalidateQueries({ queryKey: ['tickets', 'mine'] })
        if ((payload as { ticket_id?: string }).ticket_id)
          qc.invalidateQueries({ queryKey: ['tickets', (payload as { ticket_id: string }).ticket_id] })
        invalidateDashboards()
        push({ event_type: type, message: `Ticket ${(payload as { ticket_id?: string }).ticket_id ?? ''} updated`, timestamp })
        break
      case WS_EVENTS.TICKET_REASSIGNED: {
        const p = payload as { ticket_id?: string; technician_id?: string }
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        if (p.ticket_id) qc.invalidateQueries({ queryKey: ['tickets', p.ticket_id] })
        invalidateDashboards()
        const message = `Ticket ${p.ticket_id ?? ''} reassigned to you — previous technician didn't acknowledge in time`
        push({ event_type: type, message, timestamp })
        if (p.technician_id === userId) showToast(message, 'warning')
        break
      }
      case WS_EVENTS.ASSIGNMENT_OVERDUE: {
        const p = payload as { ticket_id?: string }
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        invalidateDashboards()
        push({ event_type: type, message: `Ticket ${p.ticket_id ?? ''} is overdue for acknowledgment`, timestamp })
        break
      }
      case WS_EVENTS.LOW_CONFIDENCE_QUEUED:
        qc.invalidateQueries({ queryKey: ['tickets', 'low-confidence'] })
        invalidateDashboards()
        push({ event_type: type, message: `Low-confidence ticket queued for review`, timestamp })
        break
      case WS_EVENTS.ABSTENTION_FLAGGED:
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        invalidateDashboards()
        push({ event_type: type, message: `Ticket flagged — no KB coverage`, timestamp })
        break
      case WS_EVENTS.SLA_WARNING:
        invalidateDashboards()
        push({ event_type: type, message: `SLA warning on ticket ${(payload as { ticket_id?: string }).ticket_id ?? ''}`, timestamp })
        break
      case WS_EVENTS.SLA_BREACHED:
        invalidateDashboards()
        push({ event_type: type, message: `SLA breached on ticket ${(payload as { ticket_id?: string }).ticket_id ?? ''}`, timestamp })
        break
      case WS_EVENTS.AURA_COMMENT_POSTED:
        qc.invalidateQueries({ queryKey: ['tickets', (payload as { ticket_id?: string }).ticket_id ?? ''] })
        qc.invalidateQueries({ queryKey: ['tickets', 'mine'] })
        invalidateDashboards()
        push({ event_type: type, message: `AURA posted a comment on ticket ${(payload as { ticket_id?: string }).ticket_id ?? ''}`, timestamp })
        break
      case WS_EVENTS.TICKET_CLAIMED: {
        const p = payload as { ticket_id?: string; claimed_by?: string }
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        invalidateDashboards()
        if (p.claimed_by !== userId)
          push({ event_type: type, message: `Ticket ${p.ticket_id ?? ''} claimed by a teammate`, timestamp })
        break
      }
      case WS_EVENTS.TICKET_UNCLAIMED:
        qc.invalidateQueries({ queryKey: ['tickets', 'queue'] })
        invalidateDashboards()
        break
      case WS_EVENTS.USER_UPDATED: {
        // An admin edited this exact user's profile — sync the locally
        // cached display_name/email/role instead of leaving it stale in
        // authStore until the next login.
        const p = payload as { user_id?: string; display_name?: string; email?: string; role?: string; team_id?: string | null }
        if (p.user_id === userId) {
          updateProfile({ display_name: p.display_name, email: p.email, role: p.role, team_id: p.team_id })
        }
        break
      }
      case WS_EVENTS.INGESTION_PROGRESS:
      case WS_EVENTS.INGESTION_COMPLETE:
        useIngestionProgressStore.getState().setLatest(payload as unknown as IngestionProgressEvent)
        qc.invalidateQueries({ queryKey: ['admin', 'qdrant', 'stats'] })
        qc.invalidateQueries({ queryKey: ['ingestion', 'status'] })
        qc.invalidateQueries({ queryKey: ['ingestion', 'runs'] })
        invalidateDashboards()
        break
      default:
        break
    }
  }, [qc, setKillSwitch, push, showToast, userId, updateProfile])

  const connect = useCallback(() => {
    if (!accessToken || !userId) return
    const url = `${WS_BASE}/api/v1/ws/${userId}?token=${accessToken}`
    const ws  = new WebSocket(url)
    wsRef.current = ws

    ws.onopen    = () => { attemptRef.current = 0 }
    ws.onmessage = (e) => {
      try { dispatch(JSON.parse(e.data) as WSEvent) } catch { /* ignore malformed */ }
    }
    ws.onclose = (e) => {
      if (e.code === 1000) return  // normal closure — logout
      const delay = BACKOFF[Math.min(attemptRef.current++, BACKOFF.length - 1)]
      setTimeout(connect, delay)
    }
    ws.onerror = () => ws.close()
  }, [accessToken, userId, dispatch])

  const disconnect = useCallback(() => {
    wsRef.current?.close(1000)
    wsRef.current = null
  }, [])

  useEffect(() => {
    if (!accessToken) return
    // Small delay avoids StrictMode double-mount creating two connections
    const t = setTimeout(connect, 50)
    return () => {
      clearTimeout(t)
      disconnect()
    }
  }, [accessToken, connect, disconnect])

  return { disconnect }
}
