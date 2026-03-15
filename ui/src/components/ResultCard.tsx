/**
 * ResultCard — renders a single search result with syntax-highlighted code,
 * similarity score badge, and copy actions.
 */
import { useState } from 'react'
import { Copy, Check, FileText, ChevronDown, ChevronRight } from 'lucide-react'
import { cn, scoreBgColor, formatScore, copyToClipboard, formatAsMarkdown } from '@/lib/utils'
import type { SearchResultItem } from '@/api/client'

interface ResultCardProps {
  result: SearchResultItem
  index: number
}

export default function ResultCard({ result, index }: ResultCardProps) {
  const [copied, setCopied] = useState<'snippet' | 'markdown' | null>(null)
  const [graphOpen, setGraphOpen] = useState(false)

  const hasGraph = result.relationships && result.relationships.length > 0

  async function handleCopy(type: 'snippet' | 'markdown') {
    const text =
      type === 'markdown'
        ? formatAsMarkdown({
            file: result.file,
            lines: result.lines,
            kind: result.kind,
            score: result.score,
            name: result.name,
            content_preview: result.content_preview,
          })
        : result.content_preview ?? result.snippet ?? ''

    await copyToClipboard(text)
    setCopied(type)
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 border-b border-slate-700/40 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <FileText size={13} className="shrink-0 text-slate-500" />
            <span className="truncate font-mono text-xs text-slate-300">
              {result.file}
            </span>
            <span className="text-xs text-slate-500">·</span>
            <span className="text-xs text-slate-500">lines {result.lines}</span>
          </div>
          {result.name && (
            <div className="mt-1 flex items-center gap-2">
              <span className="font-mono text-sm font-medium text-slate-100">
                {result.name}
              </span>
              <span className="text-xs text-slate-500">{result.kind}</span>
            </div>
          )}
        </div>

        {/* Score badge + visual bar */}
        <div className="shrink-0 flex flex-col items-end gap-1.5">
          <span className={cn('badge font-mono text-xs', scoreBgColor(result.score))}>
            {formatScore(result.score)}
          </span>
          {/* Thin progress bar giving at-a-glance score reading */}
          <div className="h-0.5 w-10 rounded-full bg-slate-700 overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full',
                result.score >= 0.80 ? 'bg-green-500' :
                result.score >= 0.40 ? 'bg-yellow-500' : 'bg-red-500',
              )}
              style={{ width: `${Math.round(result.score * 100)}%` }}
            />
          </div>
          <span className="text-xs text-slate-600">#{index + 1}</span>
        </div>
      </div>

      {/* Code block */}
      {(result.content_preview || result.snippet) && (
        <div className="relative group">
          <pre className="overflow-x-auto bg-slate-900/60 px-4 py-3 text-xs leading-relaxed font-mono">
            <code className="text-slate-200 whitespace-pre">
              {result.content_preview || result.snippet}
            </code>
          </pre>

          {/* Copy actions — visible at reduced opacity, full opacity on hover/focus.
               Always rendered so keyboard and touch users can reach them. */}
          <div className="absolute right-2 top-2 flex gap-1 opacity-40 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <button
              onClick={() => handleCopy('snippet')}
              className="btn-ghost rounded px-2 py-1 text-xs"
              title="Copy code"
            >
              {copied === 'snippet' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
              <span className="ml-1">Copy</span>
            </button>
            <button
              onClick={() => handleCopy('markdown')}
              className="btn-ghost rounded px-2 py-1 text-xs"
              title="Copy as Markdown (paste into AI chat)"
            >
              {copied === 'markdown' ? <Check size={12} className="text-green-400" /> : <FileText size={12} />}
              <span className="ml-1">Markdown</span>
            </button>
          </div>
        </div>
      )}

      {/* Footer: docstring, tags, graph relationships */}
      <div className="px-4 py-2 space-y-1.5 border-t border-slate-700/30">
        {result.docstring && (
          <p className="text-xs text-slate-400 italic line-clamp-2">{result.docstring}</p>
        )}

        {result.tags && result.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {result.tags.map((tag) => (
              <span key={tag} className="badge bg-slate-700/50 text-slate-400 text-xs">
                {tag}
              </span>
            ))}
          </div>
        )}

        {hasGraph && (
          <div>
            <button
              onClick={() => setGraphOpen(!graphOpen)}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              {graphOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              Graph context ({result.relationships!.length} relationships)
            </button>
            {graphOpen && (
              <div className="mt-1.5 space-y-0.5">
                {result.relationships!.map((rel, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="badge bg-slate-800 text-slate-400">{rel.type}</span>
                    <span className="text-slate-600">{rel.direction === 'outgoing' ? '→' : '←'}</span>
                    <span className="font-mono truncate text-slate-400">{rel.target}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
