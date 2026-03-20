/**
 * SearchPanel — the primary search interface.
 *
 * Features:
 * - Natural language query input with Ctrl+Enter shortcut
 * - k (results count) slider
 * - Optional file pattern and chunk type filters
 * - Recent query history chips for quick re-use
 * - Results rendered with ResultCard
 * - "Export all as Markdown" and "Export as AI prompt" buttons
 * - Sparkles icon for the AI-powered search action
 * - aria-live regions for accessible status announcements
 */
import { useState, useRef, useEffect, useId, type KeyboardEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Sparkles, SlidersHorizontal, FileDown, Loader2, Search, BrainCircuit } from 'lucide-react'
import { api, type SearchResponse } from '@/api/client'
import { useStore } from '@/store/useStore'
import ResultCard from '@/components/ResultCard'
import InfoPopover from '@/components/InfoPopover'
import { copyToClipboard, formatAsMarkdown, formatAsPromptContext } from '@/lib/utils'

const CHUNK_TYPES = ['', 'function', 'class', 'method', 'module', 'interface', 'struct']

/** Skeleton placeholder shown while a search is in-flight. */
function ResultSkeleton() {
  return (
    <div className="card overflow-hidden animate-pulse" aria-hidden="true">
      <div className="flex items-start justify-between gap-3 border-b border-slate-700/40 px-4 py-3">
        <div className="flex-1 space-y-2">
          <div className="h-3 w-2/3 rounded bg-slate-700/60" />
          <div className="h-4 w-1/3 rounded bg-slate-700/40" />
        </div>
        <div className="h-5 w-12 rounded-full bg-slate-700/60" />
      </div>
      <div className="bg-slate-900/60 px-4 py-3 space-y-1.5">
        <div className="h-3 w-full rounded bg-slate-700/40" />
        <div className="h-3 w-5/6 rounded bg-slate-700/40" />
        <div className="h-3 w-4/6 rounded bg-slate-700/40" />
      </div>
    </div>
  )
}

export default function SearchPanel() {
  const { lastQuery, setLastQuery, queryHistory, addToHistory } = useStore()
  const [query, setQuery] = useState(lastQuery)
  const [k, setK] = useState(5)
  const [filePattern, setFilePattern] = useState('')
  const [chunkType, setChunkType] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [exportedAll, setExportedAll] = useState<'markdown' | 'prompt' | null>(null)
  const queryRef = useRef<HTMLTextAreaElement>(null)
  const resultsRef = useRef<HTMLDivElement>(null)
  const requestIdRef = useRef(0)
  const statusId = useId()
  const sliderId = useId()

  // Auto-focus the search textarea on initial mount.
  useEffect(() => {
    queryRef.current?.focus()
  }, [])

  const mutation = useMutation({
    // Pass the query as an explicit argument so history-triggered searches
    // are never affected by stale React state from a concurrent setState call.
    mutationFn: (searchQuery: string) => {
      const id = ++requestIdRef.current
      return api.search({
        query: searchQuery,
        k,
        file_pattern: filePattern || undefined,
        chunk_type: chunkType || undefined,
        include_context: true,
      }).then((data) => ({ data, id }))
    },
    onSuccess: ({ data, id }, searchQuery) => {
      // Discard if a newer request or a clear has occurred since this one started.
      if (id !== requestIdRef.current) return
      setResults(data)
      setLastQuery(searchQuery)
      addToHistory(searchQuery)
    },
  })

  function handleSearch() {
    if (!query.trim()) return
    mutation.mutate(query)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      // Enter submits; Shift+Enter inserts a newline (standard across platforms).
      e.preventDefault()
      handleSearch()
    }
  }

  function applyHistoryQuery(q: string) {
    setQuery(q)
    // Pass `q` directly so the mutation doesn't depend on React's async state flush.
    mutation.mutate(q)
  }

  async function exportAllMarkdown() {
    if (!results?.results.length) return
    const md = results.results
      .map((r) => formatAsMarkdown({
        file: r.file,
        lines: r.lines,
        kind: r.kind,
        score: r.score,
        name: r.name,
        content_preview: r.content_preview,
        start_line: r.start_line,
      }))
      .join('\n\n---\n\n')
    try {
      await copyToClipboard(md)
    } catch {
      return
    }
    setExportedAll('markdown')
    setTimeout(() => setExportedAll(null), 2000)
  }

  async function exportAsPrompt() {
    if (!results?.results.length) return
    const ctx = formatAsPromptContext(
      results.results.map((r) => ({
        file: r.file,
        lines: r.lines,
        kind: r.kind,
        score: r.score,
        name: r.name,
        content_preview: r.content_preview,
        start_line: r.start_line,
      })),
      results.query,
    )
    try {
      await copyToClipboard(ctx)
    } catch {
      return
    }
    setExportedAll('prompt')
    setTimeout(() => setExportedAll(null), 2000)
  }

  // Status text announced to screen readers when results change.
  const statusText = mutation.isPending
    ? 'Searching…'
    : mutation.isError
      ? `Search failed: ${mutation.error?.message}`
      : results
        ? `${results.result_count} result${results.result_count !== 1 ? 's' : ''} for "${results.query}"`
        : ''

  return (
    <div className="flex h-full flex-col">
      {/* Hidden live region — announces search status to screen readers */}
      <div
        id={statusId}
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {statusText}
      </div>

      {/* Search form */}
      <div className="border-b border-slate-700/50 bg-[#13151f] p-4 space-y-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-3 text-slate-500" aria-hidden="true" />
          <textarea
            ref={queryRef}
            id="search-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search your codebase semantically… (Enter to search)"
            rows={2}
            aria-label="Search query"
            aria-describedby={statusId}
            className="input pl-9 pr-14 resize-none"
          />
          <button
            onClick={handleSearch}
            disabled={!query.trim() || mutation.isPending}
            className="btn-primary absolute bottom-2.5 right-2.5 px-3 py-2"
            aria-label={mutation.isPending ? 'Searching…' : 'Search'}
          >
            {mutation.isPending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles size={14} aria-hidden="true" />
            )}
          </button>
        </div>

        {/* k slider + filter toggle */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <InfoPopover
              title="Results slider"
              triggerMode="hover"
              trigger={<span className="text-xs text-slate-500">Results: {k}</span>}
              panelClassName="w-64"
            >
              <p>
                Controls how many top matches to return. Higher values broaden recall but can add latency.
                Start around 5-10, then increase if key files are missing.
              </p>
            </InfoPopover>
            <input
              id={sliderId}
              type="range"
              min={1}
              max={20}
              value={k}
              onChange={(e) => setK(Number(e.target.value))}
              aria-label={`Number of results: ${k}`}
              className="h-1.5 w-28 accent-indigo-500"
            />
          </div>
          <button
            onClick={() => setShowFilters(!showFilters)}
            aria-expanded={showFilters}
            aria-controls="search-filters"
            className={`btn-ghost text-xs ${showFilters ? 'text-indigo-400' : ''}`}
          >
            <SlidersHorizontal size={13} aria-hidden="true" />
            Filters
          </button>
        </div>

        {/* Optional filters */}
        <div id="search-filters" hidden={!showFilters}>
          {showFilters && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label flex items-center gap-1.5" htmlFor="filter-file-pattern">
                  File pattern (glob)
                  <InfoPopover title="File pattern cheat sheet">
                    <div className="space-y-2">
                      <p>Use glob patterns to narrow which files are searched.</p>
                      <ul className="space-y-1 text-slate-400">
                        <li><code>**/*.py</code> - Python files only</li>
                        <li><code>{'ui/src/**/*.{ts,tsx}'}</code> - frontend TS/TSX</li>
                        <li><code>**/tests/**/*.py</code> - Python test files</li>
                        <li><code>**/*service*.py</code> - service-related Python modules</li>
                      </ul>
                      <p className="text-slate-500">
                        Leave empty to search all indexed files.
                      </p>
                    </div>
                  </InfoPopover>
                </label>
                <input
                  id="filter-file-pattern"
                  type="text"
                  value={filePattern}
                  onChange={(e) => setFilePattern(e.target.value)}
                  placeholder="e.g. **/*.py"
                  className="input text-xs"
                />
              </div>
              <div>
                <label className="label flex items-center gap-1.5" htmlFor="filter-chunk-type">
                  Chunk type
                  <InfoPopover title="Chunk type cheat sheet">
                    <div className="space-y-2">
                      <p>Filter results by code structure when you know what you want.</p>
                      <ul className="space-y-1 text-slate-400">
                        <li><code>function</code> - standalone functions/helpers</li>
                        <li><code>class</code> / <code>interface</code> / <code>struct</code> - type definitions</li>
                        <li><code>method</code> - behavior inside classes/structs</li>
                        <li><code>module</code> - top-level module/file chunks</li>
                      </ul>
                      <p className="text-slate-500">
                        Use <code>Any type</code> first when exploring broadly.
                      </p>
                    </div>
                  </InfoPopover>
                </label>
                <select
                  id="filter-chunk-type"
                  value={chunkType}
                  onChange={(e) => setChunkType(e.target.value)}
                  className="input text-xs"
                >
                  {CHUNK_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t || 'Any type'}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Recent query history chips */}
        {queryHistory.length > 0 && !mutation.isPending && (
          <div className="flex flex-wrap gap-1.5 pt-0.5" aria-label="Recent searches">
            {queryHistory.map((q) => (
              <button
                key={q}
                onClick={() => applyHistoryQuery(q)}
                className="btn-ghost rounded-full px-2.5 py-0.5 text-xs border border-slate-700/60 hover:border-indigo-500/50"
                title={`Search again: ${q}`}
                aria-label={`Repeat search: ${q}`}
              >
                {q.length > 40 ? `${q.slice(0, 40)}…` : q}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div ref={resultsRef} className="flex-1 overflow-y-auto p-4">
        {mutation.isError && (
          <div
            role="alert"
            className="rounded-md border border-red-800/50 bg-red-900/20 p-3 text-sm text-red-300"
          >
            {mutation.error.message}
          </div>
        )}

        {/* Skeleton cards while a search is in-flight */}
        {mutation.isPending && (
          <div className="space-y-4" aria-label="Loading results">
            {Array.from({ length: k }).map((_, i) => (
              <ResultSkeleton key={i} />
            ))}
          </div>
        )}

        {results && !mutation.isPending && (
          <div className="space-y-4">
            {/* Results header */}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <p className="text-sm text-slate-400">
                {results.result_count} result{results.result_count !== 1 ? 's' : ''} for{' '}
                <span className="font-medium text-slate-200">"{results.query}"</span>
                {results.graph_enriched && (
                  <span className="ml-2 badge bg-indigo-900/40 text-indigo-300">graph</span>
                )}
              </p>
              {results.result_count > 0 && (
                <div className="flex gap-1.5">
                  {/* Export all results as Markdown */}
                  <button
                    onClick={exportAllMarkdown}
                    className="btn-ghost text-xs"
                    aria-label={exportedAll === 'markdown' ? 'All results copied as Markdown' : 'Copy all results as Markdown'}
                    title="Copy all results as Markdown"
                  >
                    <FileDown size={13} aria-hidden="true" />
                    <span aria-live="polite">
                      {exportedAll === 'markdown' ? 'Copied!' : 'Export Markdown'}
                    </span>
                  </button>
                  {/* Export all results as AI prompt context */}
                  <button
                    onClick={exportAsPrompt}
                    className="btn-ghost text-xs"
                    aria-label={exportedAll === 'prompt' ? 'AI prompt context copied' : 'Copy all results as AI prompt context'}
                    title="Copy as AI prompt context — paste directly into your AI chat"
                  >
                    <BrainCircuit size={13} aria-hidden="true" />
                    <span aria-live="polite">
                      {exportedAll === 'prompt' ? 'Copied!' : 'Copy as Prompt'}
                    </span>
                  </button>
                </div>
              )}
            </div>

            {results.result_count === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">
                No results found. Try a different query or re-index the project.
              </p>
            ) : (
              <ol className="space-y-4 list-none" aria-label="Search results">
                {results.results.map((result, i) => (
                  <li key={result.chunk_id}>
                    <ResultCard result={result} index={i} />
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}

        {!results && !mutation.isPending && !mutation.isError && (
          <div className="flex flex-col items-center justify-center h-full text-center py-16">
            <Search size={40} className="text-slate-700 mb-4" aria-hidden="true" />
            <p className="text-slate-500 text-sm max-w-xs">
              Enter a natural language query above to semantically search your
              indexed codebase.
            </p>
            <p className="text-slate-600 text-xs mt-2">
              Press{' '}
              <kbd className="rounded bg-slate-800 px-1 py-0.5 font-mono text-slate-400">
                Enter
              </kbd>{' '}
              to search,{' '}
              <kbd className="rounded bg-slate-800 px-1 py-0.5 font-mono text-slate-400">
                Shift+Enter
              </kbd>{' '}
              for a new line
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
