/**
 * Global UI state store using Zustand.
 *
 * Keeps only truly global state here (active tab, last search query, etc.).
 * Server state (API data) lives in TanStack Query hooks, not this store.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ActiveTab = 'search' | 'health' | 'projects' | 'settings'

const MAX_HISTORY = 5

interface AppStore {
  activeTab: ActiveTab
  setActiveTab: (tab: ActiveTab) => void

  lastQuery: string
  setLastQuery: (q: string) => void

  /** Recent unique queries, newest-first. Capped at MAX_HISTORY entries. */
  queryHistory: string[]
  addToHistory: (q: string) => void

  sidebarOpen: boolean
  toggleSidebar: () => void
}

export const useStore = create<AppStore>()(
  persist(
    (set) => ({
      activeTab: 'search',
      setActiveTab: (tab) => set({ activeTab: tab }),

      lastQuery: '',
      setLastQuery: (q) => set({ lastQuery: q }),

      /** Recent unique queries, newest-first. Capped at MAX_HISTORY entries. */
      queryHistory: [],
      addToHistory: (q) =>
        set((s) => {
          const trimmed = q.trim()
          if (!trimmed) return s
          // Deduplicate: remove existing entry for same query, then prepend.
          const filtered = s.queryHistory.filter((h) => h !== trimmed)
          return { queryHistory: [trimmed, ...filtered].slice(0, MAX_HISTORY) }
        }),

      sidebarOpen: true,
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
    }),
    {
      name: 'agent-context-ui',
      // Only persist fields meaningful across page refreshes.
      partialize: (s) => ({
        queryHistory: s.queryHistory,
        lastQuery: s.lastQuery,
        sidebarOpen: s.sidebarOpen,
      }),
    },
  ),
)
