/**
 * Global UI state store using Zustand.
 *
 * Keeps only truly global state here (active tab, last search query, etc.).
 * Server state (API data) lives in TanStack Query hooks, not this store.
 */

import { create } from 'zustand'

export type ActiveTab = 'search' | 'health' | 'projects' | 'settings'

interface AppStore {
  activeTab: ActiveTab
  setActiveTab: (tab: ActiveTab) => void

  lastQuery: string
  setLastQuery: (q: string) => void

  sidebarOpen: boolean
  toggleSidebar: () => void
}

export const useStore = create<AppStore>((set) => ({
  activeTab: 'search',
  setActiveTab: (tab) => set({ activeTab: tab }),

  lastQuery: '',
  setLastQuery: (q) => set({ lastQuery: q }),

  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}))
