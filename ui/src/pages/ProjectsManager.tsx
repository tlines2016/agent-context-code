/**
 * ProjectsManager — list indexed projects, switch active project, trigger re-index.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, RefreshCw, ArrowRight, Loader2, XCircle, Clock, Box } from 'lucide-react'
import { api, type ProjectInfo } from '@/api/client'
import { cn } from '@/lib/utils'

export default function ProjectsManager() {
  const qc = useQueryClient()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['projects'],
    queryFn: api.listProjects,
  })

  const switchMutation = useMutation({
    mutationFn: (path: string) => api.switchProject(path),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['index-status'] })
    },
  })

  const reindexMutation = useMutation({
    mutationFn: (path: string) => api.runIndex({ directory_path: path, incremental: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-slate-500" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-red-800/50 bg-red-900/20 p-4 text-sm text-red-300 flex items-center gap-2">
          <XCircle size={16} />
          {(error as Error).message}
        </div>
      </div>
    )
  }

  const { projects, current_project } = data!

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderOpen size={18} className="text-indigo-400" />
          <h1 className="text-lg font-semibold text-slate-100">Projects</h1>
          <span className="badge bg-slate-700 text-slate-400">{projects.length}</span>
        </div>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['projects'] })}
          className="btn-secondary"
        >
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="py-16 text-center">
          <FolderOpen size={40} className="text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500 text-sm">No projects indexed yet.</p>
          <p className="text-slate-600 text-xs mt-1">
            Run <code className="font-mono">index_directory()</code> via the MCP tool or CLI to index a project.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <ProjectRow
              key={project.project_hash}
              project={project}
              isActive={current_project === project.project_path}
              onSwitch={() => switchMutation.mutate(project.project_path)}
              onReindex={() => reindexMutation.mutate(project.project_path)}
              switching={switchMutation.isPending && switchMutation.variables === project.project_path}
              reindexing={reindexMutation.isPending && reindexMutation.variables === project.project_path}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface ProjectRowProps {
  project: ProjectInfo
  isActive: boolean
  onSwitch: () => void
  onReindex: () => void
  switching: boolean
  reindexing: boolean
}

function ProjectRow({ project, isActive, onSwitch, onReindex, switching, reindexing }: ProjectRowProps) {
  const stats = project.index_stats

  return (
    <div className={cn('card p-4 transition-all', isActive && 'border-indigo-500/50 bg-indigo-900/10')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            {isActive && (
              <span className="badge bg-indigo-600/30 text-indigo-300 text-xs">Active</span>
            )}
            <span className="font-medium text-slate-100 truncate">{project.project_name}</span>
          </div>
          <p className="font-mono text-xs text-slate-500 truncate">{project.project_path}</p>

          {stats && (
            <div className="flex flex-wrap gap-3 mt-2 text-xs text-slate-500">
              {stats.total_chunks !== undefined && (
                <span className="flex items-center gap-1">
                  <Box size={11} />
                  {stats.total_chunks.toLocaleString()} chunks
                </span>
              )}
              {stats.storage_size_mb !== undefined && (
                <span>{stats.storage_size_mb.toFixed(1)} MB</span>
              )}
              {stats.last_indexed && (
                <span className="flex items-center gap-1">
                  <Clock size={11} />
                  {new Date(stats.last_indexed).toLocaleDateString()}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-2 shrink-0">
          <button
            onClick={onReindex}
            disabled={reindexing}
            className="btn-secondary text-xs"
            title="Re-index this project"
          >
            {reindexing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Re-index
          </button>
          {!isActive && (
            <button
              onClick={onSwitch}
              disabled={switching}
              className="btn-primary text-xs"
              title="Set as active project"
            >
              {switching ? <Loader2 size={12} className="animate-spin" /> : <ArrowRight size={12} />}
              Switch
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
