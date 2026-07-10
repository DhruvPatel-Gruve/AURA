import { create } from 'zustand'
import type { Notification } from '@/api/types'

interface NotificationState {
  notifications:  Notification[]
  unreadCount:    number

  push:         (n: Omit<Notification, 'id' | 'read'>) => void
  markAllRead:  () => void
  markRead:     (id: string) => void
}

let _idSeq = 0

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  unreadCount:   0,

  push: (n) => {
    const notification: Notification = { ...n, id: String(++_idSeq), read: false }
    set((s) => ({
      notifications: [notification, ...s.notifications].slice(0, 100),
      unreadCount:   s.unreadCount + 1,
    }))
  },

  markAllRead: () =>
    set((s) => ({
      notifications: s.notifications.map((n) => ({ ...n, read: true })),
      unreadCount:   0,
    })),

  markRead: (id) =>
    set((s) => ({
      notifications: s.notifications.map((n) => (n.id === id ? { ...n, read: true } : n)),
      unreadCount:   Math.max(0, s.unreadCount - 1),
    })),
}))
