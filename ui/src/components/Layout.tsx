/**
 * Top-level sidebar navigation layout.
 */
import { useState, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Search,
  Activity,
  FolderOpen,
  Settings,
  Menu,
  Cpu,
  RefreshCw,
  Loader2,
  CheckCircle,
  Database,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useStore, type ActiveTab } from '@/store/useStore'
import { api } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog'

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
        <nav aria-label="Main navigation" className="flex-1 space-y-1 p-2 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              aria-current={activeTab === item.id ? 'page' : undefined}
              aria-label={!sidebarOpen ? item.label : undefined}
              className={cn(
                'w-full',
                activeTab === item.id ? 'nav-item-active' : 'nav-item',
                !sidebarOpen && 'justify-center px-2',
              )}
              title={!sidebarOpen ? item.label : undefined}
            >
              <span className="shrink-0" aria-hidden="true">{item.icon}</span>
              {sidebarOpen && <span>{item.label}</span>}
            </button>
          ))}
        </nav>

        {/* Footer — restart controls */}
        <SidebarFooter expanded={sidebarOpen} />
      </aside>

      {/* Main content area */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  )
}

function SidebarFooter({ expanded }: { expanded: boolean }) {
  const [dashboardStatus, setDashboardStatus] = useState<'idle' | 'restarting'>('idle')
  const [mcpStatus, setMcpStatus] = useState<'idle' | 'stopping' | 'done' | 'error'>('idle')
  const [engineStatus, setEngineStatus] = useState<'idle' | 'restarting'>('idle')
  const [engineConfirmOpen, setEngineConfirmOpen] = useState(false)

  const dashboardMutation = useMutation({
    mutationFn: api.restartServer,
    onMutate: () => {
      setDashboardStatus('restarting')
      // Server shuts down after responding — onSuccess may never fire if the
      // connection is severed before the response is fully received.  Reset
      // the button after a timeout so it doesn't stay stuck on "Restarting…".
      setTimeout(() => setDashboardStatus('idle'), 8000)
    },
    onError: () => setDashboardStatus('idle'),
  })

  const mcpMutation = useMutation({
    mutationFn: api.restartMcp,
    onSuccess: (data) => {
      setMcpStatus(data.stopped > 0 ? 'done' : 'idle')
      if (data.stopped > 0) setTimeout(() => setMcpStatus('idle'), 3000)
    },
    onError: () => {
      setMcpStatus('error')
      setTimeout(() => setMcpStatus('idle'), 3000)
    },
  })

  async function handleEngineRestart() {
    setEngineConfirmOpen(false)
    setEngineStatus('restarting')
    try {
      // 1. Stop the MCP server processes first (quick, returns immediately)
      await api.restartMcp()
      // 2. Restart the dashboard server (reloads CodeSearchServer, models, config)
      await api.restartServer()
    } catch {
      // Expected — the dashboard restart severs the connection before responding.
    }
    // Reset after timeout (server will be back up in a few seconds)
    setTimeout(() => setEngineStatus('idle'), 8000)
  }

  const anyBusy = dashboardStatus !== 'idle' || mcpStatus === 'stopping' || engineStatus !== 'idle'

  if (!expanded) {
    return (
      <div className="border-t border-slate-700/50 p-2 space-y-1">
        <ConfirmDialog
          open={engineConfirmOpen}
          title="Restart Search Engine"
          message="This will restart the entire code search infrastructure — the dashboard server, model runtime, and MCP server (if running). Active searches and in-progress indexing will be interrupted. Claude Code will automatically reconnect to the MCP server on next use."
          confirmLabel="Restart Engine"
          onCancel={() => setEngineConfirmOpen(false)}
          onConfirm={handleEngineRestart}
        />
        <button
          onClick={() => dashboardMutation.mutate()}
          disabled={anyBusy}
          className="w-full flex justify-center rounded-md p-1.5 text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
          title="Restart Dashboard"
          aria-label="Restart Dashboard"
        >
          {dashboardStatus === 'restarting'
            ? <Loader2 size={14} className="animate-spin" />
            : <RefreshCw size={14} />
          }
        </button>
        <button
          onClick={() => { setMcpStatus('stopping'); mcpMutation.mutate() }}
          disabled={anyBusy}
          className="w-full flex justify-center rounded-md p-1.5 text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
          title="Restart MCP Server (Claude Code)"
          aria-label="Restart MCP Server"
        >
          {mcpStatus === 'stopping'
            ? <Loader2 size={14} className="animate-spin" />
            : mcpStatus === 'done'
              ? <CheckCircle size={14} className="text-green-400" />
              : <Cpu size={14} />
          }
        </button>
        <button
          onClick={() => setEngineConfirmOpen(true)}
          disabled={anyBusy}
          className="w-full flex justify-center rounded-md p-1.5 text-amber-600 hover:text-amber-400 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
          title="Restart Search Engine (full restart)"
          aria-label="Restart Search Engine"
        >
          {engineStatus === 'restarting'
            ? <Loader2 size={14} className="animate-spin" />
            : <Database size={14} />
          }
        </button>
      </div>
    )
  }

  return (
    <div className="border-t border-slate-700/50 p-2 space-y-1">
      <ConfirmDialog
        open={engineConfirmOpen}
        title="Restart Search Engine"
        message="This will restart the entire code search infrastructure — the dashboard server, model runtime, and MCP server (if running). Active searches and in-progress indexing will be interrupted. Claude Code will automatically reconnect to the MCP server on next use."
        confirmLabel="Restart Engine"
        onCancel={() => setEngineConfirmOpen(false)}
        onConfirm={handleEngineRestart}
      />
      <button
        onClick={() => dashboardMutation.mutate()}
        disabled={anyBusy}
        className="w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
        title="Restart the dashboard server to apply config changes"
      >
        {dashboardStatus === 'restarting'
          ? <Loader2 size={12} className="animate-spin shrink-0" />
          : <RefreshCw size={12} className="shrink-0" />
        }
        <span>{dashboardStatus === 'restarting' ? 'Restarting…' : 'Restart Dashboard'}</span>
      </button>
      <button
        onClick={() => { setMcpStatus('stopping'); mcpMutation.mutate() }}
        disabled={anyBusy}
        className="w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
        title="Stop the MCP server process — Claude Code will restart it automatically"
      >
        {mcpStatus === 'stopping'
          ? <Loader2 size={12} className="animate-spin shrink-0" />
          : mcpStatus === 'done'
            ? <CheckCircle size={12} className="text-green-400 shrink-0" />
            : <Cpu size={12} className="shrink-0" />
        }
        <span className="truncate">
          {mcpStatus === 'stopping' ? 'Stopping…' : mcpStatus === 'done' ? 'Stopped' : 'Restart MCP'}
        </span>
        <span className="ml-auto text-[10px] text-slate-600 shrink-0">Claude</span>
      </button>
      <button
        onClick={() => setEngineConfirmOpen(true)}
        disabled={anyBusy}
        className="w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-amber-600 hover:text-amber-400 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
        title="Full restart — reloads models, config, and MCP server"
      >
        {engineStatus === 'restarting'
          ? <Loader2 size={12} className="animate-spin shrink-0" />
          : <Database size={12} className="shrink-0" />
        }
        <span>{engineStatus === 'restarting' ? 'Restarting…' : 'Restart Engine'}</span>
      </button>
    </div>
  )
}
