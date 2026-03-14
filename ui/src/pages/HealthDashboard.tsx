/**
 * HealthDashboard — shows index statistics, sync status, and re-index controls.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  PieChart,
  Pie,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import {
  Activity,
  RefreshCw,
  Trash2,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Loader2,
} from 'lucide-react'
import { api } from '@/api/client'
import { cn } from '@/lib/utils'

const CHART_COLORS = [
  '#6366f1', '#818cf8', '#a5b4fc', '#c7d2fe',
  '#34d399', '#6ee7b7', '#fbbf24', '#f87171',
]

function SyncBadge({ status }: { status: 'synced' | 'degraded' }) {
  if (status === 'synced') {
    return (
      <span className="flex items-center gap-1 text-green-400 text-sm">
        <CheckCircle size={14} /> Synced
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1 text-yellow-400 text-sm">
      <AlertTriangle size={14} /> Degraded
    </span>
  )
}

export default function HealthDashboard() {
  const qc = useQueryClient()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['index-status'],
    queryFn: api.indexStatus,
    refetchInterval: 60_000,
  })

  const clearMutation = useMutation({
    mutationFn: api.clearIndex,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['index-status'] }),
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

  const stats = data!.index_statistics
  const model = data!.model_information

  // Prepare chart data from language/type breakdowns if available
  const langData = stats.languages
    ? Object.entries(stats.languages)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 8)
        .map(([name, value]) => ({ name, value }))
    : []

  const typeData = stats.chunk_types
    ? Object.entries(stats.chunk_types)
        .sort(([, a], [, b]) => b - a)
        .map(([name, value]) => ({ name, value }))
    : []

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={18} className="text-indigo-400" />
          <h1 className="text-lg font-semibold text-slate-100">Index Health</h1>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['index-status'] })}
            className="btn-secondary"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
          <button
            onClick={() => {
              if (confirm('Clear the entire index? This cannot be undone.')) {
                clearMutation.mutate()
              }
            }}
            disabled={clearMutation.isPending}
            className="btn-danger"
          >
            {clearMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
            Clear Index
          </button>
        </div>
      </div>

      {/* Status overview cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Chunks" value={stats.total_chunks?.toLocaleString() ?? '—'} />
        <StatCard label="Storage" value={stats.storage_size_mb ? `${stats.storage_size_mb.toFixed(1)} MB` : '—'} />
        <StatCard label="Model" value={model.model_name?.split('/').pop() ?? '—'} small />
        <StatCard label="Sync Status" value={<SyncBadge status={data!.sync_status} />} />
      </div>

      {data!.degraded_reason && (
        <div className="rounded-md border border-yellow-700/50 bg-yellow-900/20 p-3 text-xs text-yellow-300 flex items-center gap-2">
          <AlertTriangle size={14} />
          {data!.degraded_reason}
        </div>
      )}

      {/* Language breakdown */}
      {langData.length > 0 && (
        <div className="card p-4">
          <h2 className="text-sm font-medium text-slate-300 mb-3">Chunks by Language</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={langData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#1e2130', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#e2e8f0' }}
              />
              <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                {langData.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Chunk type breakdown */}
      {typeData.length > 0 && (
        <div className="card p-4">
          <h2 className="text-sm font-medium text-slate-300 mb-3">Chunks by Type</h2>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={typeData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={80}
                label={({ name, percent }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
                labelLine={{ stroke: '#475569' }}
              >
                {typeData.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: '#1e2130', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
              />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 12, color: '#94a3b8' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Index details */}
      <div className="card divide-y divide-slate-700/40">
        <DetailRow label="Vector store" value={data!.vector_indexed ? '✓ Indexed' : '✗ Empty'} ok={data!.vector_indexed} />
        <DetailRow label="Graph store" value={data!.graph_indexed ? '✓ Indexed' : '✗ Empty'} ok={data!.graph_indexed} />
        <DetailRow label="Merkle snapshot" value={data!.snapshot_exists ? '✓ Present' : '✗ Missing'} ok={data!.snapshot_exists} />
        <DetailRow label="Storage directory" value={data!.storage_directory} mono />
        <DetailRow label="Embedding dimension" value={model.embedding_dimension?.toString() ?? '—'} />
        <DetailRow label="Compute device" value={model.device ?? '—'} />
        {stats.last_indexed && (
          <DetailRow label="Last indexed" value={new Date(stats.last_indexed).toLocaleString()} />
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, small }: { label: string; value: React.ReactNode; small?: boolean }) {
  return (
    <div className="card px-4 py-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={cn('font-semibold text-slate-100', small ? 'text-sm truncate' : 'text-lg')}>
        {value}
      </p>
    </div>
  )
}

function DetailRow({ label, value, ok, mono }: { label: string; value: string; ok?: boolean; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 text-sm">
      <span className="text-slate-400">{label}</span>
      <span
        className={cn(
          mono ? 'font-mono text-xs' : '',
          ok === true ? 'text-green-400' : ok === false ? 'text-red-400' : 'text-slate-300',
        )}
      >
        {value}
      </span>
    </div>
  )
}
