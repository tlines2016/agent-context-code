/**
 * Root application component — renders the sidebar layout and the active page.
 */
import { Component, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import Layout from '@/components/Layout'
import SearchPanel from '@/pages/SearchPanel'
import HealthDashboard from '@/pages/HealthDashboard'
import ProjectsManager from '@/pages/ProjectsManager'
import SettingsForm from '@/pages/SettingsForm'
import { useStore } from '@/store/useStore'
import { api } from '@/api/client'

// ---------------------------------------------------------------------------
// ErrorBoundary — prevents a render error in any panel from white-screening
// the entire app. Class component required because React has no hook equivalent.
// ---------------------------------------------------------------------------

interface ErrorBoundaryState {
  error: Error | null
}

class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  handleReset = () => this.setState({ error: null })

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
          <p className="text-sm font-semibold text-red-400">Something went wrong</p>
          <p className="max-w-sm text-xs text-slate-500">{this.state.error.message}</p>
          <button
            onClick={this.handleReset}
            className="btn-secondary text-xs"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// ---------------------------------------------------------------------------

function StatusBar() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
  })

  return (
    <div className="fixed bottom-3 right-3 z-40">
      <div className="flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-[#13151f]/90 backdrop-blur-sm px-3 py-1 text-xs text-slate-400 shadow-lg">
        {data ? (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-green-500 inline-block" />
            <span>v{data.version}</span>
            <span className="text-slate-600">·</span>
            <span className="text-green-400">connected</span>
          </>
        ) : (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-yellow-500 inline-block animate-pulse" />
            <span>connecting…</span>
          </>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const { activeTab } = useStore()

  function renderPage() {
    switch (activeTab) {
      case 'search':   return <SearchPanel />
      case 'health':   return <HealthDashboard />
      case 'projects': return <ProjectsManager />
      case 'settings': return <SettingsForm />
    }
  }

  return (
    <>
      <Layout>
        {/* key forces remount on tab switch, triggering the fade-in animation */}
        <ErrorBoundary key={activeTab}>
          <div className="page-animate h-full">
            {renderPage()}
          </div>
        </ErrorBoundary>
      </Layout>
      <StatusBar />
    </>
  )
}
