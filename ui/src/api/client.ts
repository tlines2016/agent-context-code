/**
 * Typed HTTP client for the agent-context-local REST API.
 *
 * All functions return plain objects or throw an Error with a descriptive
 * message so callers (TanStack Query hooks) can display meaningful feedback.
 */

// Base URL — empty string means "same origin" which works for both the
// production FastAPI server and the Vite dev proxy configured in vite.config.ts.
const BASE = ''

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  timeoutMs = 30_000,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s`)
    }
    throw err
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const err = await res.json()
      detail = err.detail ?? err.error ?? detail
    } catch {
      // ignore JSON parse errors on error responses
    }
    throw new Error(detail)
  }

  return res.json() as Promise<T>
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string
  version: string
}

export interface SearchResultItem {
  file: string
  lines: string
  kind: string
  score: number
  chunk_id: string
  name?: string
  snippet?: string
  vector_score?: number
  relationships?: Array<{ type: string; target: string; direction: string }>
  content_preview?: string
  start_line?: number
  end_line?: number
  docstring?: string
  tags?: string[]
}

export interface SearchResponse {
  query: string
  project?: string
  results: SearchResultItem[]
  graph_enriched: boolean
  result_count: number
}

export interface SearchRequest {
  query: string
  k?: number
  file_pattern?: string
  chunk_type?: string
  include_context?: boolean
  project_path?: string
  max_results_per_file?: number
}

export interface ProjectInfo {
  project_name: string
  project_path: string
  project_hash: string
  created_at?: string
  index_stats?: {
    total_chunks?: number
    last_indexed?: string
    storage_size_mb?: number
    version_count?: number
  }
}

export interface ProjectsResponse {
  projects: ProjectInfo[]
  count: number
  current_project?: string
}

export interface IndexStatusResponse {
  index_statistics: {
    total_chunks: number
    version_count?: number
    storage_size_mb?: number
    last_indexed?: string
    languages?: Record<string, number>
    chunk_types?: Record<string, number>
  }
  model_information: {
    model_name: string
    embedding_dimension?: number
    device?: string
  }
  storage_directory: string
  sync_status: 'synced' | 'degraded'
  vector_indexed: boolean
  graph_indexed: boolean
  snapshot_exists: boolean
  degraded_reason?: string
  graph_statistics?: {
    total_symbols?: number
    total_relationships?: number
    languages?: Record<string, number>
  }
}

export interface IndexRequest {
  directory_path: string
  project_name?: string
  file_patterns?: string[]
  incremental?: boolean
}

export interface EmbeddingModelInfo {
  model_name: string
  short_name: string
  description: string
  recommended_for: string
  embedding_dimension?: number
  gpu_default: boolean
}

export interface ModelsResponse {
  models: EmbeddingModelInfo[]
  count: number
  gpu_available: boolean
}

export interface RerankerModelInfo {
  model_name: string
  short_name: string
  description: string
  recommended_for: string
  gpu_default: boolean
}

export interface RerankersResponse {
  rerankers: RerankerModelInfo[]
  count: number
}

export interface Settings {
  embedding_model?: { model_name?: string; embedding_dimension?: number }
  reranker?: {
    model_name?: string
    enabled?: boolean
    recall_k?: number
    min_reranker_score?: number
  }
  idle_offload_minutes?: number
  idle_unload_minutes?: number
  _storage_dir?: string
}

export interface SettingsUpdate {
  embedding_model?: { model_name?: string }
  reranker?: {
    enabled?: boolean
    model_name?: string
    recall_k?: number
    min_reranker_score?: number
  }
  idle?: {
    idle_offload_minutes?: number
    idle_unload_minutes?: number
  }
}

// ── API functions ─────────────────────────────────────────────────────────────

export const api = {
  health: () => request<HealthResponse>('GET', '/api/v1/health'),

  search: (req: SearchRequest) =>
    request<SearchResponse>('POST', '/api/v1/search', req),

  listProjects: () => request<ProjectsResponse>('GET', '/api/v1/projects'),

  switchProject: (project_path: string) =>
    request<{ success: boolean; message: string }>('POST', '/api/v1/projects/switch', { project_path }),

  indexStatus: () => request<IndexStatusResponse>('GET', '/api/v1/index/status'),

  runIndex: (req: IndexRequest) =>
    request<{ success?: boolean; chunks_indexed?: number; message?: string }>('POST', '/api/v1/index/run', req),

  clearIndex: () =>
    request<{ success: boolean; message: string }>('DELETE', '/api/v1/index/clear'),

  getSettings: () => request<Settings>('GET', '/api/v1/settings'),

  updateSettings: (update: SettingsUpdate) =>
    request<Settings>('PUT', '/api/v1/settings', update),

  listModels: () => request<ModelsResponse>('GET', '/api/v1/models'),

  listRerankers: () => request<RerankersResponse>('GET', '/api/v1/rerankers'),

  restartServer: () =>
    request<{ message: string }>('POST', '/api/v1/server/restart'),
}
