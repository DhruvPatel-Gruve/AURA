import { create } from 'zustand'

export type ToastVariant = 'info' | 'success' | 'warning'

export interface Toast {
  id:       string
  message:  string
  variant:  ToastVariant
}

interface ToastState {
  toasts: Toast[]
  show:   (message: string, variant?: ToastVariant) => void
  dismiss: (id: string) => void
}

let _idSeq = 0

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],

  show: (message, variant = 'info') => {
    const id = String(++_idSeq)
    set((s) => ({ toasts: [...s.toasts, { id, message, variant }] }))
  },

  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
