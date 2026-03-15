/**
 * SearchPanel — the primary search interface.
 *
 * Features:
 * - Natural language query input with Ctrl+Enter shortcut
 * - k (results count) slider
 * - Optional file pattern and chunk type filters
 * - Results rendered with ResultCard
 * - "Export all as Markdown" button
 */
import { useState, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Search, SlidersHorizontal, FileDown, Loader2 } from 'lucide-react'
import { api, type SearchResponse } from '@/api/client'
import { useStore } from '@/store/useStore'
import ResultCard from '@/components/ResultCard'
import { copyToClipboard, formatAsMarkdown } from '@/lib/utils'

const CHUNK_TYPES = ['', 'function', 'class', 'method', 'module', 'interface', 'struct']

/** Skeleton placeholder shown while a search is in-flight. */
function ResultSkeleton() {
  return (
    <div className="card overflow-hidden animate-pulse">
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
  const { lastQuery, setLastQuery } = useStore()
  const [query, setQuery] = useState(lastQuery)
  const [k, setK] = useState(5)
  const [filePattern, setFilePattern] = useState('')
  const [chunkType, setChunkType] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [exportedAll, setExportedAll] = useState(false)
  const queryRef = useRef<HTMLTextAreaElement>(null)

  const mutation = useMutation({
    mutationFn: () =>
      api.search({
        query,
        k,
        file_pattern: filePattern || undefined,
        chunk_type: chunkType || undefined,
        include_context: true,
      }),
    onSuccess: (data) => {
      setResults(data)
      setLastQuery(query)
    },
  })

  function handleSearch() {
    if (!query.trim()) return
    mutation.mutate()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      handleSearch()
    }
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
      }))
      .join('\n\n---\n\n')
    await copyToClipboard(md)
    setExportedAll(true)
    setTimeout(() => setExportedAll(false), 2000)
  }

  return (
    <div className="flex h-full flex-col">
      {/* Search form */}
      <div className="border-b border-slate-700/50 bg-[#13151f] p-4 space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-3 text-slate-500" />
            <textarea
              ref={queryRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search your codebase semantically… (Ctrl+Enter to search)"
              rows={2}
              className="input pl-9 resize-none"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={!query.trim() || mutation.isPending}
            className="btn-primary self-stretch px-5"
          >
            {mutation.isPending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Search size={16} />
            )}
          </button>
        </div>

        {/* k slider + filter toggle */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">Results: {k}</label>
            <input
              type="range"
              min={1}
              max={20}
              value={k}
              onChange={(e) => setK(Number(e.target.value))}
              className="h-1.5 w-28 accent-indigo-500"
            />
          </div>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`btn-ghost text-xs ${showFilters ? 'text-indigo-400' : ''}`}
          >
            <SlidersHorizontal size={13} />
            Filters
          </button>
        </div>

        {/* Optional filters */}
        {showFilters && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">File pattern (glob)</label>
              <input
                type="text"
                value={filePattern}
                onChange={(e) => setFilePattern(e.target.value)}
                placeholder="e.g. **/*.py"
                className="input text-xs"
              />
            </div>
            <div>
              <label className="label">Chunk type</label>
              <select
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

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-4">
        {mutation.isError && (
          <div className="rounded-md border border-red-800/50 bg-red-900/20 p-3 text-sm text-red-300">
            {mutation.error.message}
          </div>
        )}

        {/* Skeleton cards while a search is in-flight */}
        {mutation.isPending && (
          <div className="space-y-4">
            {Array.from({ length: k }).map((_, i) => (
              <ResultSkeleton key={i} />
            ))}
          </div>
        )}

        {results && !mutation.isPending && (
          <div className="space-y-4">
            {/* Results header */}
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-400">
                {results.result_count} result{results.result_count !== 1 ? 's' : ''} for{' '}
                <span className="font-medium text-slate-200">"{results.query}"</span>
                {results.graph_enriched && (
                  <span className="ml-2 badge bg-indigo-900/40 text-indigo-300">graph</span>
                )}
              </p>
              {results.result_count > 0 && (
                <button onClick={exportAllMarkdown} className="btn-ghost text-xs">
                  <FileDown size={13} />
                  {exportedAll ? 'Copied!' : 'Export all'}
                </button>
              )}
            </div>

            {results.result_count === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">
                No results found. Try a different query or re-index the project.
              </p>
            ) : (
              results.results.map((result, i) => (
                <ResultCard key={result.chunk_id} result={result} index={i} />
              ))
            )}
          </div>
        )}

        {!results && !mutation.isPending && !mutation.isError && (
          <div className="flex flex-col items-center justify-center h-full text-center py-16">
            <Search size={40} className="text-slate-700 mb-4" />
            <p className="text-slate-500 text-sm max-w-xs">
              Enter a natural language query above to semantically search your
              indexed codebase.
            </p>
            <p className="text-slate-600 text-xs mt-2">
              Tip: press <kbd className="rounded bg-slate-800 px-1 py-0.5 font-mono text-slate-400">Ctrl+Enter</kbd> to search
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
