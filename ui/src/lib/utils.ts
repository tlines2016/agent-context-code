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

interface FormatMarkdownParams {
  file: string
  lines: string
  kind: string
  score: number
  name?: string
  content_preview?: string
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
