/**
 * ResultCard — renders a single search result with syntax-highlighted code,
 * similarity score badge, and copy actions.
 */
import { useState } from 'react'
import { Copy, Check, FileText, ChevronDown, ChevronRight, Link } from 'lucide-react'
import { cn, scoreBgColor, formatScore, copyToClipboard, formatAsMarkdown, formatFilePath } from '@/lib/utils'
import type { SearchResultItem } from '@/api/client'

interface ResultCardProps {
  result: SearchResultItem
  index: number
}

export default function ResultCard({ result, index }: ResultCardProps) {
  const [copied, setCopied] = useState<'snippet' | 'markdown' | 'path' | null>(null)
  const [graphOpen, setGraphOpen] = useState(false)

  const hasGraph = result.relationships && result.relationships.length > 0
  const hasCode = !!(result.content_preview || result.snippet)

  async function handleCopy(type: 'snippet' | 'markdown' | 'path') {
    let text: string
    if (type === 'markdown') {
      text = formatAsMarkdown({
        file: result.file,
        lines: result.lines,
        kind: result.kind,
        score: result.score,
        name: result.name,
        content_preview: result.content_preview,
        start_line: result.start_line,
      })
    } else if (type === 'path') {
      text = formatFilePath(result.file, result.start_line, result.lines)
    } else {
      text = result.content_preview ?? result.snippet ?? ''
    }

    await copyToClipboard(text)
    setCopied(type)
    setTimeout(() => setCopied(null), 2000)
  }

  const scorePercent = Math.round(result.score * 100)

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 border-b border-slate-700/40 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <FileText size={13} className="shrink-0 text-slate-500" aria-hidden="true" />
            <span className="truncate font-mono text-xs text-slate-300">
              {result.file}
            </span>
            <span className="text-xs text-slate-500" aria-hidden="true">·</span>
            <span className="text-xs text-slate-500">lines {result.lines}</span>
            {/* Copy file path reference (e.g. src/foo.py:10) */}
            <button
              onClick={() => handleCopy('path')}
              className="btn-ghost rounded px-1.5 py-0.5 text-xs opacity-50 hover:opacity-100 focus-visible:opacity-100 transition-opacity"
              aria-label={`Copy file path reference: ${formatFilePath(result.file, result.start_line, result.lines)}`}
              title="Copy file path with line number"
            >
              {copied === 'path' ? (
                <Check size={11} className="text-green-400" aria-hidden="true" />
              ) : (
                <Link size={11} aria-hidden="true" />
              )}
              <span className="ml-1 sr-only">
                {copied === 'path' ? 'Copied!' : 'Copy path'}
              </span>
            </button>
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
          <span
            className={cn('badge font-mono text-xs', scoreBgColor(result.score))}
            aria-label={`Similarity score ${scorePercent}%`}
          >
            {formatScore(result.score)}
          </span>
          {/* Thin progress bar giving at-a-glance score reading */}
          <div
            role="progressbar"
            aria-valuenow={scorePercent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Score ${scorePercent}%`}
            className="h-0.5 w-10 rounded-full bg-slate-700 overflow-hidden"
          >
            <div
              className={cn(
                'h-full rounded-full',
                result.score >= 0.80 ? 'bg-green-500' :
                result.score >= 0.40 ? 'bg-yellow-500' : 'bg-red-500',
              )}
              style={{ width: `${scorePercent}%` }}
              aria-hidden="true"
            />
          </div>
          <span className="text-xs text-slate-600" aria-label={`Result number ${index + 1}`}>
            #{index + 1}
          </span>
        </div>
      </div>

      {/* Code block */}
      {hasCode && (
        <div className="relative group">
          <pre className="overflow-x-auto bg-slate-900/60 px-4 py-3 text-xs leading-relaxed font-mono">
            <code className="text-slate-200 whitespace-pre">
              {result.content_preview || result.snippet}
            </code>
          </pre>

          {/* Copy actions — visible at reduced opacity, full opacity on hover/focus.
               Always rendered so keyboard and touch users can reach them. */}
          <div
            className="absolute right-2 top-2 flex gap-1 opacity-40 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
            // Announce copy feedback to screen readers via aria-live on each button
          >
            <button
              onClick={() => handleCopy('snippet')}
              className="btn-ghost rounded px-2 py-1 text-xs"
              aria-label={copied === 'snippet' ? 'Code copied to clipboard' : 'Copy code snippet'}
              title="Copy code"
            >
              {copied === 'snippet' ? (
                <Check size={12} className="text-green-400" aria-hidden="true" />
              ) : (
                <Copy size={12} aria-hidden="true" />
              )}
              <span className="ml-1" aria-live="polite">
                {copied === 'snippet' ? 'Copied!' : 'Copy'}
              </span>
            </button>
            <button
              onClick={() => handleCopy('markdown')}
              className="btn-ghost rounded px-2 py-1 text-xs"
              aria-label={copied === 'markdown' ? 'Markdown copied to clipboard' : 'Copy as Markdown for AI chat'}
              title="Copy as Markdown (paste into AI chat)"
            >
              {copied === 'markdown' ? (
                <Check size={12} className="text-green-400" aria-hidden="true" />
              ) : (
                <FileText size={12} aria-hidden="true" />
              )}
              <span className="ml-1" aria-live="polite">
                {copied === 'markdown' ? 'Copied!' : 'Markdown'}
              </span>
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
          <div className="flex flex-wrap gap-1" role="list" aria-label="Tags">
            {result.tags.map((tag) => (
              <span key={tag} role="listitem" className="badge bg-slate-700/50 text-slate-400 text-xs">
                {tag}
              </span>
            ))}
          </div>
        )}

        {hasGraph && (
          <div>
            <button
              onClick={() => setGraphOpen(!graphOpen)}
              aria-expanded={graphOpen}
              aria-controls={`graph-${result.chunk_id}`}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              {graphOpen ? (
                <ChevronDown size={12} aria-hidden="true" />
              ) : (
                <ChevronRight size={12} aria-hidden="true" />
              )}
              Graph context ({result.relationships!.length} relationships)
            </button>
            {graphOpen && (
              <div id={`graph-${result.chunk_id}`} className="mt-1.5 space-y-0.5">
                {result.relationships!.map((rel, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="badge bg-slate-800 text-slate-400">{rel.type}</span>
                    {/* Arrow is purely visual; direction word is announced by screen readers via sr-only */}
                    <span aria-hidden="true" className="text-slate-600">
                      {rel.direction === 'outgoing' ? '→' : '←'}
                    </span>
                    <span className="sr-only">
                      {rel.direction === 'outgoing' ? 'to' : 'from'}
                    </span>
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
