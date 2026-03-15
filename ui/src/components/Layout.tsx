/**
 * Top-level sidebar navigation layout.
 */
import { type ReactNode } from 'react'
import {
  Search,
  Activity,
  FolderOpen,
  Settings,
  Menu,
  Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useStore, type ActiveTab } from '@/store/useStore'

interface NavItem {
  id: ActiveTab
  label: string
  icon: ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { id: 'search',   label: 'Search',    icon: <Search size={16} /> },
  { id: 'health',   label: 'Index Health', icon: <Activity size={16} /> },
  { id: 'projects', label: 'Projects',  icon: <FolderOpen size={16} /> },
  { id: 'settings', label: 'Settings',  icon: <Settings size={16} /> },
]

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { activeTab, setActiveTab, sidebarOpen, toggleSidebar } = useStore()

  return (
    <div className="flex h-screen overflow-hidden bg-[#0f1117]">
      {/* Sidebar */}
      <aside
        className={cn(
          'flex flex-col border-r border-slate-700/50 bg-[#13151f] transition-all duration-200',
          sidebarOpen ? 'w-52' : 'w-14',
        )}
      >
        {/* Logo / header */}
        <div className="flex h-14 items-center gap-2.5 border-b border-slate-700/50 px-3">
          <button
            onClick={toggleSidebar}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-700/50 hover:text-slate-200"
            aria-label="Toggle sidebar"
          >
            <Menu size={16} />
          </button>
          {sidebarOpen ? (
            <div className="flex items-center gap-1.5 min-w-0">
              <Cpu size={16} className="shrink-0 text-indigo-400" />
              <span className="truncate text-sm font-semibold text-slate-100">
                Agent Context
              </span>
            </div>
          ) : (
            /* Show the app icon even when collapsed so the sidebar is identifiable */
            <Cpu size={16} className="shrink-0 text-indigo-400" />
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 p-2 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={cn(
                'w-full',
                activeTab === item.id ? 'nav-item-active' : 'nav-item',
                !sidebarOpen && 'justify-center px-2',
              )}
              title={!sidebarOpen ? item.label : undefined}
            >
              <span className="shrink-0">{item.icon}</span>
              {sidebarOpen && <span>{item.label}</span>}
            </button>
          ))}
        </nav>

        {/* Footer — only shown when expanded */}
        {sidebarOpen && (
          <div className="border-t border-slate-700/50 p-3 text-xs text-slate-600">
            100% local · no data leaves your machine
          </div>
        )}
      </aside>

      {/* Main content area */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  )
}
