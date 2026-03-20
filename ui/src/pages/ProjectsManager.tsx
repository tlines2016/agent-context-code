/**
 * ProjectsManager — list indexed projects, switch active project, trigger re-index.
 *
 * Supports multi-select for bulk Remove and Clear Index operations.
 * Re-index and Switch are single-project actions only.
 */
import { useCallback, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, RefreshCw, ArrowRight, Loader2, XCircle, Clock, Box, Search, Trash2, Eraser, CheckSquare, Square, MinusSquare } from 'lucide-react'
import { api, type ProjectInfo } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog'
import { cn } from '@/lib/utils'

type PendingAction =
  | { kind: 'clear' | 'remove'; project: ProjectInfo }
  | { kind: 'bulk-clear' | 'bulk-remove'; paths: string[]; names: string[] }

export default function ProjectsManager() {
  const qc = useQueryClient()
  const [searchTerm, setSearchTerm] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [actionErrorMessage, setActionErrorMessage] = useState<string | null>(null)
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set())
  const scrollRestoreRef = useRef<number | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['projects'],
    queryFn: api.listProjects,
  })

  /** Save current scroll position of the main content area. */
  const saveScrollPosition = useCallback(() => {
    const main = document.querySelector('main')
    scrollRestoreRef.current = main?.scrollTop ?? null
  }, [])

  /** Restore saved scroll position after React re-renders. */
  const restoreScrollPosition = useCallback(() => {
    if (scrollRestoreRef.current === null) return
    const pos = scrollRestoreRef.current
    scrollRestoreRef.current = null
    requestAnimationFrame(() => {
      const main = document.querySelector('main')
      if (main) main.scrollTop = pos
    })
  }, [])

  const invalidateAndRestore = useCallback(async () => {
    setActionErrorMessage(null)
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['projects'] }),
      qc.invalidateQueries({ queryKey: ['index-status'] }),
    ])
    restoreScrollPosition()
  }, [qc, restoreScrollPosition])

  const switchMutation = useMutation({
    mutationFn: (path: string) => api.switchProject(path),
    onSuccess: () => {
      setActionErrorMessage(null)
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['index-status'] })
    },
    onError: (error: Error) => setActionErrorMessage(error.message),
  })

  const reindexMutation = useMutation({
    mutationFn: (path: string) => api.runIndex({ directory_path: path, incremental: true }),
    onSuccess: () => {
      setActionErrorMessage(null)
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: (error: Error) => setActionErrorMessage(error.message),
  })

  const clearProjectIndexMutation = useMutation({
    mutationFn: (path: string) => api.clearProjectIndex(path),
    onSuccess: () => invalidateAndRestore(),
    onError: (error: Error) => setActionErrorMessage(error.message),
  })

  const removeProjectMutation = useMutation({
    mutationFn: (path: string) => api.removeProject(path),
    onSuccess: () => invalidateAndRestore(),
    onError: (error: Error) => setActionErrorMessage(error.message),
  })

  const bulkRemoveMutation = useMutation({
    mutationFn: async (paths: string[]) => {
      const results = await Promise.allSettled(paths.map((p) => api.removeProject(p)))
      const failures = results.filter((r) => r.status === 'rejected')
      if (failures.length > 0) {
        throw new Error(`${failures.length} of ${paths.length} removals failed`)
      }
    },
    onSuccess: () => {
      setSelectedPaths(new Set())
      invalidateAndRestore()
    },
    onError: (error: Error) => {
      setSelectedPaths(new Set())
      setActionErrorMessage(error.message)
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['index-status'] })
      restoreScrollPosition()
    },
  })

  const bulkClearMutation = useMutation({
    mutationFn: async (paths: string[]) => {
      const results = await Promise.allSettled(paths.map((p) => api.clearProjectIndex(p)))
      const failures = results.filter((r) => r.status === 'rejected')
      if (failures.length > 0) {
        throw new Error(`${failures.length} of ${paths.length} clears failed`)
      }
    },
    onSuccess: () => {
      setSelectedPaths(new Set())
      invalidateAndRestore()
    },
    onError: (error: Error) => {
      setSelectedPaths(new Set())
      setActionErrorMessage(error.message)
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['index-status'] })
      restoreScrollPosition()
    },
  })

  const projects = data?.projects ?? []
  const currentProject = data?.current_project
  const filteredProjects = useMemo(() => {
    const needle = searchTerm.trim().toLowerCase()
    if (!needle) return projects
    return projects.filter((project) =>
      project.project_name.toLowerCase().includes(needle)
      || project.project_path.toLowerCase().includes(needle),
    )
  }, [projects, searchTerm])

  const anyActionPending = switchMutation.isPending
    || reindexMutation.isPending
    || clearProjectIndexMutation.isPending
    || removeProjectMutation.isPending
    || bulkRemoveMutation.isPending
    || bulkClearMutation.isPending

  // Selection helpers
  const filteredPaths = useMemo(() => new Set(filteredProjects.map((p) => p.project_path)), [filteredProjects])
  const visibleSelected = useMemo(() => {
    const s = new Set<string>()
    for (const p of selectedPaths) {
      if (filteredPaths.has(p)) s.add(p)
    }
    return s
  }, [selectedPaths, filteredPaths])

  const allVisibleSelected = filteredProjects.length > 0 && visibleSelected.size === filteredProjects.length
  const someVisibleSelected = visibleSelected.size > 0 && !allVisibleSelected

  function toggleSelect(path: string) {
    setSelectedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function toggleSelectAll() {
    if (allVisibleSelected) {
      // Deselect all visible
      setSelectedPaths((prev) => {
        const next = new Set(prev)
        for (const p of filteredPaths) next.delete(p)
        return next
      })
    } else {
      // Select all visible
      setSelectedPaths((prev) => {
        const next = new Set(prev)
        for (const p of filteredPaths) next.add(p)
        return next
      })
    }
  }

  function getConfirmTitle(): string {
    if (!pendingAction) return ''
    switch (pendingAction.kind) {
      case 'remove': return 'Remove Project'
      case 'clear': return 'Clear Project Index'
      case 'bulk-remove': return `Remove ${pendingAction.paths.length} Projects`
      case 'bulk-clear': return `Clear Index for ${pendingAction.paths.length} Projects`
    }
  }

  function getConfirmMessage(): string {
    if (!pendingAction) return ''
    switch (pendingAction.kind) {
      case 'remove':
        return `Remove "${pendingAction.project.project_name}" and all local index data? This cannot be undone.`
      case 'clear':
        return `Clear indexed artifacts for "${pendingAction.project.project_name}" while keeping the project entry?`
      case 'bulk-remove':
        return `Remove ${pendingAction.paths.length} selected projects and all their index data? This cannot be undone.\n\n${pendingAction.names.join(', ')}`
      case 'bulk-clear':
        return `Clear indexed artifacts for ${pendingAction.paths.length} selected projects while keeping the project entries?\n\n${pendingAction.names.join(', ')}`
    }
  }

  function getConfirmLabel(): string {
    if (!pendingAction) return 'Confirm'
    switch (pendingAction.kind) {
      case 'remove': return 'Remove Project'
      case 'clear': return 'Clear Index'
      case 'bulk-remove': return `Remove ${pendingAction.paths.length} Projects`
      case 'bulk-clear': return `Clear ${pendingAction.paths.length} Indexes`
    }
  }

  function handleConfirm() {
    if (!pendingAction) return
    saveScrollPosition()
    switch (pendingAction.kind) {
      case 'remove':
        removeProjectMutation.mutate(pendingAction.project.project_path)
        break
      case 'clear':
        clearProjectIndexMutation.mutate(pendingAction.project.project_path)
        break
      case 'bulk-remove':
        bulkRemoveMutation.mutate(pendingAction.paths)
        break
      case 'bulk-clear':
        bulkClearMutation.mutate(pendingAction.paths)
        break
    }
    setPendingAction(null)
  }

  function startBulkAction(kind: 'bulk-remove' | 'bulk-clear') {
    const paths = [...visibleSelected]
    const names = paths.map((p) => {
      const proj = projects.find((pr) => pr.project_path === p)
      return proj?.project_name ?? p
    })
    setPendingAction({ kind, paths, names })
  }

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

  return (
    <div className="p-6 space-y-4">
      <ConfirmDialog
        open={pendingAction !== null}
        title={getConfirmTitle()}
        message={getConfirmMessage()}
        confirmLabel={getConfirmLabel()}
        onCancel={() => setPendingAction(null)}
        onConfirm={handleConfirm}
      />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderOpen size={18} className="text-indigo-400" />
          <h1 className="text-lg font-semibold text-slate-100">Projects</h1>
          <span className="badge bg-slate-700 text-slate-400">{filteredProjects.length}</span>
        </div>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['projects'] })}
          className="btn-secondary"
        >
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      <div className="relative">
        <Search size={14} className="pointer-events-none absolute left-3 top-2.5 text-slate-500" />
        <input
          type="text"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          placeholder="Search projects by name or path…"
          className="input pl-9"
          aria-label="Search indexed projects"
        />
      </div>

      {/* Bulk action bar — shown when any projects are selected */}
      {visibleSelected.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-indigo-500/30 bg-indigo-900/15 px-4 py-2.5">
          <span className="text-sm text-indigo-300 font-medium">
            {visibleSelected.size} selected
          </span>
          <div className="flex gap-2 ml-auto">
            <button
              onClick={() => startBulkAction('bulk-clear')}
              disabled={anyActionPending}
              className="btn-danger text-xs"
            >
              <Eraser size={12} />
              Clear Index
            </button>
            <button
              onClick={() => startBulkAction('bulk-remove')}
              disabled={anyActionPending}
              className="btn-danger text-xs"
            >
              <Trash2 size={12} />
              Remove
            </button>
            <button
              onClick={() => setSelectedPaths(new Set())}
              className="btn-ghost text-xs"
            >
              Deselect All
            </button>
          </div>
        </div>
      )}

      {actionErrorMessage && (
        <div className="rounded-md border border-red-800/50 bg-red-900/20 p-3 text-sm text-red-300">
          {actionErrorMessage}
        </div>
      )}

      {projects.length === 0 ? (
        <div className="py-16 text-center">
          <FolderOpen size={40} className="text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500 text-sm">No projects indexed yet.</p>
          <p className="text-slate-600 text-xs mt-1">
            Run <code className="font-mono">index_directory()</code> via the MCP tool or CLI to index a project.
          </p>
        </div>
      ) : filteredProjects.length === 0 ? (
        <div className="py-16 text-center">
          <Search size={36} className="text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">No projects match your search.</p>
        </div>
      ) : (
        <>
          {/* Select-all row */}
          <div className="flex items-center gap-2 px-1">
            <button
              onClick={toggleSelectAll}
              className="text-slate-400 hover:text-slate-200 transition-colors"
              aria-label={allVisibleSelected ? 'Deselect all projects' : 'Select all projects'}
              title={allVisibleSelected ? 'Deselect all' : 'Select all'}
            >
              {allVisibleSelected ? (
                <CheckSquare size={16} className="text-indigo-400" />
              ) : someVisibleSelected ? (
                <MinusSquare size={16} className="text-indigo-400" />
              ) : (
                <Square size={16} />
              )}
            </button>
            <span className="text-xs text-slate-500">
              {allVisibleSelected ? 'Deselect all' : 'Select all'}
            </span>
          </div>

          <div className="space-y-3">
            {filteredProjects.map((project) => (
              <ProjectRow
                key={project.project_hash}
                project={project}
                isActive={currentProject === project.project_path}
                selected={selectedPaths.has(project.project_path)}
                onToggleSelect={() => toggleSelect(project.project_path)}
                onSwitch={() => switchMutation.mutate(project.project_path)}
                onReindex={() => reindexMutation.mutate(project.project_path)}
                onClearIndex={() => {
                  saveScrollPosition()
                  setPendingAction({ kind: 'clear', project })
                }}
                onRemove={() => {
                  saveScrollPosition()
                  setPendingAction({ kind: 'remove', project })
                }}
                switching={switchMutation.isPending && switchMutation.variables === project.project_path}
                reindexing={reindexMutation.isPending && reindexMutation.variables === project.project_path}
                actionBusy={anyActionPending}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

interface ProjectRowProps {
  project: ProjectInfo
  isActive: boolean
  selected: boolean
  onToggleSelect: () => void
  onSwitch: () => void
  onReindex: () => void
  onClearIndex: () => void
  onRemove: () => void
  switching: boolean
  reindexing: boolean
  actionBusy: boolean
}

function ProjectRow({
  project,
  isActive,
  selected,
  onToggleSelect,
  onSwitch,
  onReindex,
  onClearIndex,
  onRemove,
  switching,
  reindexing,
  actionBusy,
}: ProjectRowProps) {
  const stats = project.index_stats

  return (
    <div className={cn('card p-4 transition-all', isActive && 'border-indigo-500/50 bg-indigo-900/10', selected && 'border-indigo-500/40 bg-indigo-900/5')}>
      <div className="flex items-start gap-3">
        {/* Selection checkbox */}
        <button
          onClick={onToggleSelect}
          className="mt-0.5 shrink-0 text-slate-400 hover:text-slate-200 transition-colors"
          aria-label={selected ? `Deselect ${project.project_name}` : `Select ${project.project_name}`}
        >
          {selected ? (
            <CheckSquare size={16} className="text-indigo-400" />
          ) : (
            <Square size={16} />
          )}
        </button>

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
            disabled={reindexing || actionBusy}
            className="btn-secondary text-xs"
            title="Re-index this project"
          >
            {reindexing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Re-index
          </button>
          {!isActive && (
            <button
              onClick={onSwitch}
              disabled={switching || actionBusy}
              className="btn-primary text-xs"
              title="Set as active project"
            >
              {switching ? <Loader2 size={12} className="animate-spin" /> : <ArrowRight size={12} />}
              Switch
            </button>
          )}
          <button
            onClick={onClearIndex}
            disabled={actionBusy}
            className="btn-danger text-xs"
            title="Clear this project's index"
          >
            <Eraser size={12} />
            Clear Index
          </button>
          <button
            onClick={onRemove}
            disabled={actionBusy}
            className="btn-danger text-xs"
            title="Remove project entry and index data"
          >
            <Trash2 size={12} />
            Remove
          </button>
        </div>
      </div>
    </div>
  )
}
