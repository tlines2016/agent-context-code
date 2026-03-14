/**
 * Root application component — renders the sidebar layout and the active page.
 */
import { useQuery } from '@tanstack/react-query'
import Layout from '@/components/Layout'
import SearchPanel from '@/pages/SearchPanel'
import HealthDashboard from '@/pages/HealthDashboard'
import ProjectsManager from '@/pages/ProjectsManager'
import SettingsForm from '@/pages/SettingsForm'
import { useStore } from '@/store/useStore'
import { api } from '@/api/client'

function StatusBar() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
  })

  return (
    <div className="fixed bottom-0 right-0 px-3 py-1 text-xs text-slate-600 flex items-center gap-2">
      {data ? (
        <>
          <span className="h-1.5 w-1.5 rounded-full bg-green-500 inline-block" />
          v{data.version}
        </>
      ) : (
        <>
          <span className="h-1.5 w-1.5 rounded-full bg-yellow-500 inline-block animate-pulse" />
          connecting…
        </>
      )}
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
        {renderPage()}
      </Layout>
      <StatusBar />
    </>
  )
}
