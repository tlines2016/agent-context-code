/**
 * Shared utility helpers used across the dashboard components.
 *
 * Keeping all pure helpers here (no React dependencies) so they
 * can be imported by any component or page without circular-dependency risk.
 */

import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// ── Styling ───────────────────────────────────────────────────────────────────

/**
 * Merge Tailwind CSS class names safely.
 * Combines clsx (conditional classes) with tailwind-merge (deduplicate conflicts).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Return badge CSS classes for a similarity score.
 *
 * Thresholds match the score colour scale defined in tailwind.config.js:
 *   ≥ 0.80  → green (high confidence)
 *   ≥ 0.40  → yellow (medium confidence)
 *   < 0.40  → red (low confidence)
 */
export function scoreBgColor(score: number): string {
  if (score >= 0.80) return 'bg-green-900/40 text-green-300'
  if (score >= 0.40) return 'bg-yellow-900/40 text-yellow-300'
  return 'bg-red-900/40 text-red-300'
}

/** Format a 0–1 similarity score as a rounded percentage string, e.g. "87%". */
export function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`
}

// ── Clipboard ─────────────────────────────────────────────────────────────────

/**
 * Write text to the system clipboard.
 * Falls back to the legacy execCommand approach for older browser environments
 * (e.g. HTTP-only dashboards where the Clipboard API requires a secure context).
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  // Legacy fallback
  const el = document.createElement('textarea')
  el.value = text
  el.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
  document.body.appendChild(el)
  el.select()
  // execCommand is deprecated but still widely supported as a fallback.
  document.execCommand('copy')  // eslint-disable-line @typescript-eslint/no-deprecated
  document.body.removeChild(el)
}

// ── Formatting ────────────────────────────────────────────────────────────────

export interface FormatMarkdownParams {
  file: string
  lines: string
  kind: string
  score: number
  name?: string
  content_preview?: string
  start_line?: number
}

/**
 * Format a search result as a Markdown-fenced code block suitable for
 * pasting directly into an AI chat context window.
 *
 * Output shape:
 *   **File:** `path/to/file.py` · **Lines:** 10-25 · **Kind:** function · **Score:** 87%
 *
 *   ```python
 *   def my_function(): ...
 *   ```
 */
export function formatAsMarkdown({
  file,
  lines,
  kind,
  score,
  name,
  content_preview,
}: FormatMarkdownParams): string {
  const meta = [
    `**File:** \`${file}\``,
    `**Lines:** ${lines}`,
    `**Kind:** ${kind}`,
    `**Score:** ${formatScore(score)}`,
    name ? `**Name:** \`${name}\`` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  // Use the file extension as the fenced-code-block language hint
  const lang = file.split('.').pop() ?? ''
  const body = content_preview ? `\`\`\`${lang}\n${content_preview}\n\`\`\`` : ''

  return [meta, body].filter(Boolean).join('\n\n')
}

/**
 * Return a concise file-path reference including line numbers,
 * suitable for pasting into an IDE "Go to file" dialog or an AI prompt.
 *
 * Prefers the full "start-end" range from `lines` when it is available
 * (e.g. "10-25" → "src/foo.py:10-25"), falling back to just `start_line`
 * or the bare file path.
 */
export function formatFilePath(
  file: string,
  start_line?: number,
  lines?: string,
): string {
  // Use the full range from `lines` when it contains both start and end.
  if (lines && lines.includes('-')) return `${file}:${lines}`
  if (start_line !== undefined) return `${file}:${start_line}`
  if (lines) return `${file}:${lines}`
  return file
}

/**
 * Format a collection of search results as a self-contained AI prompt context
 * block.  The caller can paste this directly into an AI chat window.
 *
 * Output shape:
 *   The following code snippets are relevant to the query: "..."
 *
 *   ### 1. `path/to/file.py` — function `my_func` (lines 10-25, score 87%)
 *   ```python
 *   def my_func(): ...
 *   ```
 *   ...
 */
export function formatAsPromptContext(
  results: FormatMarkdownParams[],
  query: string,
): string {
  const header = `The following code snippets are relevant to the query: "${query}"\n`
  const sections = results
    .map((r, i) => {
      const lang = r.file.split('.').pop() ?? ''
      const title = [
        `### ${i + 1}. \`${r.file}\``,
        r.name ? `— ${r.kind} \`${r.name}\`` : `— ${r.kind}`,
        `(lines ${r.lines}, score ${formatScore(r.score)})`,
      ].join(' ')
      const body = r.content_preview
        ? `\`\`\`${lang}\n${r.content_preview}\n\`\`\``
        : ''
      return [title, body].filter(Boolean).join('\n')
    })
    .join('\n\n')

  return [header, sections].join('\n')
}
