/**
 * SettingsForm — read/write install_config.json through the REST API.
 *
 * Sections:
 * 1. Embedding Model selector
 * 2. Reranker toggle + settings
 * 3. Idle memory management thresholds
 */
import { useState, useEffect, useId, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings, Save, Loader2, CheckCircle, XCircle, AlertTriangle, RotateCw } from 'lucide-react'
import { api, type SettingsUpdate } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog'

export default function SettingsForm() {
  const qc = useQueryClient()
  // Stable IDs for label↔input associations (required for screen-reader accessibility).
  const modelId = useId()
  const rerankerModelId = useId()
  const recallKId = useId()
  const minScoreId = useId()
  const offloadMinId = useId()
  const unloadMinId = useId()

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  })

  const { data: modelsData, isLoading: modelsLoading } = useQuery({
    queryKey: ['models'],
    queryFn: api.listModels,
  })

  const { data: rerankersData, isLoading: rerankersLoading } = useQuery({
    queryKey: ['rerankers'],
    queryFn: api.listRerankers,
  })

  // Local form state — initialised from loaded settings
  const [modelName, setModelName] = useState('')
  const [rerankerEnabled, setRerankerEnabled] = useState(false)
  const [rerankerModel, setRerankerModel] = useState('')
  const [recallK, setRecallK] = useState(50)
  const [minScore, setMinScore] = useState(0.0)
  const [offloadMin, setOffloadMin] = useState(15)
  const [unloadMin, setUnloadMin] = useState(30)
  const [initialised, setInitialised] = useState(false)
  const [restartRequired, setRestartRequired] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [restartFailed, setRestartFailed] = useState(false)
  const [riskDialogOpen, setRiskDialogOpen] = useState(false)
  const [riskSummary, setRiskSummary] = useState<string[]>([])
  // Track initial model/reranker values to detect changes that require restart.
  const [savedModelName, setSavedModelName] = useState('')
  const [savedRerankerModel, setSavedRerankerModel] = useState('')

  // Hydrate form once settings load (only once to avoid overriding edits)
  useEffect(() => {
    if (settings && !initialised) {
      const em = settings.embedding_model
      setModelName(typeof em === 'object' ? em?.model_name ?? '' : em ?? '')
      const rr = settings.reranker
      if (rr) {
        setRerankerEnabled(rr.enabled ?? false)
        setRerankerModel(rr.model_name ?? '')
        setRecallK(rr.recall_k ?? 50)
        setMinScore(rr.min_reranker_score ?? 0.0)
      }
      setOffloadMin(settings.idle_offload_minutes ?? 15)
      setUnloadMin(settings.idle_unload_minutes ?? 30)
      const emName = typeof em === 'object' ? em?.model_name ?? '' : em ?? ''
      setSavedModelName(emName)
      setSavedRerankerModel(rr?.model_name ?? '')
      setInitialised(true)
    }
  }, [settings, initialised])

  const updateMutation = useMutation({
    mutationFn: (update: SettingsUpdate) => api.updateSettings(update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      // Only show restart notice when embedding model or reranker model changed.
      if (modelName !== savedModelName || rerankerModel !== savedRerankerModel) {
        setRestartRequired(true)
        setSavedModelName(modelName)
        setSavedRerankerModel(rerankerModel)
      }
    },
  })

  function submitSettings() {
    const update: SettingsUpdate = {
      embedding_model: modelName ? { model_name: modelName } : undefined,
      reranker: {
        enabled: rerankerEnabled,
        model_name: rerankerModel || undefined,
        recall_k: recallK,
        min_reranker_score: minScore,
      },
      idle: {
        idle_offload_minutes: offloadMin,
        idle_unload_minutes: unloadMin,
      },
    }
    updateMutation.mutate(update)
  }

  function handleSave() {
    const gpuAvailable = modelsData?.gpu_available ?? rerankersData?.gpu_available ?? false
    const selectedEmbedding = modelsData?.models.find((m) => m.model_name === modelName)
    const selectedReranker = rerankersData?.rerankers.find((r) => r.model_name === rerankerModel)

    const risks: string[] = []
    if (!gpuAvailable && selectedEmbedding && selectedEmbedding.cpu_feasible === false) {
      risks.push(`${selectedEmbedding.short_name || selectedEmbedding.model_name} is not CPU-feasible`)
    }
    if (!gpuAvailable && rerankerEnabled && selectedReranker && selectedReranker.cpu_feasible === false) {
      risks.push(`${selectedReranker.short_name || selectedReranker.model_name} reranker is not CPU-feasible`)
    }

    if (risks.length > 0) {
      setRiskSummary(risks)
      setRiskDialogOpen(true)
      return
    }
    submitSettings()
  }

  async function handleRestart() {
    setRestarting(true)
    setRestartFailed(false)
    try {
      await api.restartServer()
    } catch {
      // Server may drop the connection as it shuts down — that's expected.
    }
    // Poll /health until the new server instance is ready.
    const maxAttempts = 30
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        await api.health()
        // Server is back — refresh all data.
        qc.invalidateQueries()
        setRestarting(false)
        setRestartRequired(false)
        setInitialised(false)
        return
      } catch {
        // Server not ready yet — keep polling.
      }
    }
    // Restart timed out — show error feedback.
    setRestarting(false)
    setRestartFailed(true)
  }

  const isLoading = settingsLoading || modelsLoading || rerankersLoading

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <ConfirmDialog
        open={riskDialogOpen}
        title="Potentially Heavy Model Selection"
        message={`This system currently reports no GPU backend. ${riskSummary.join('; ')}. Saving may cause very slow performance or memory pressure on CPU-only machines.`}
        confirmLabel="Save Anyway"
        onCancel={() => setRiskDialogOpen(false)}
        onConfirm={() => {
          setRiskDialogOpen(false)
          submitSettings()
        }}
      />

      {/* Header */}
      <div className="flex items-center gap-2">
        <Settings size={18} className="text-indigo-400" />
        <h1 className="text-lg font-semibold text-slate-100">Settings</h1>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={16} className="animate-spin" />
          Loading settings…
        </div>
      ) : (
        <div className="space-y-6">
          {/* Restart notice */}
          {restartFailed && (
            <div role="alert" className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              <XCircle size={16} className="shrink-0" />
              <span>Server did not come back within 60 seconds. Try restarting manually via the CLI.</span>
            </div>
          )}
          {restarting && (
            <div role="alert" className="flex items-center gap-2 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-4 py-3 text-sm text-indigo-300">
              <Loader2 size={16} className="animate-spin shrink-0" />
              <span>Server is restarting — this may take up to 60 seconds while models reload…</span>
            </div>
          )}
          {restartRequired && !restarting && (
            <div role="alert" className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div className="flex flex-1 items-center justify-between gap-3">
                <span>
                  Embedding model or reranker changes take effect after restarting the server.
                </span>
                <button
                  onClick={handleRestart}
                  className="shrink-0 flex items-center gap-1.5 rounded-md bg-amber-500/20 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-500/30 transition-colors"
                >
                  <RotateCw size={12} />
                  Restart Server
                </button>
              </div>
            </div>
          )}

          {/* Embedding model */}
          <Section title="Embedding Model" description="The model used to generate code embeddings. Changing this requires re-indexing all projects.">
            <div>
              <label className="label" htmlFor={modelId}>Model</label>
              <select
                id={modelId}
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                className="input"
              >
                <option value="">— select —</option>
                {modelsData?.models.map((m) => (
                  <option key={m.model_name} value={m.model_name}>
                    {m.short_name || m.model_name}
                    {m.embedding_dimension ? ` · ${m.embedding_dimension}d` : ''}
                  </option>
                ))}
              </select>
              {(() => {
                const selected = modelsData?.models.find((m) => m.model_name === modelName)
                if (!selected) return null
                return (
                  <div className="mt-1.5 space-y-1">
                    <p className="text-xs text-slate-500">{selected.description}</p>
                    {selected.recommended_for && (
                      <p className="text-xs text-slate-500">Best for: {selected.recommended_for}</p>
                    )}
                  </div>
                )
              })()}
            </div>
          </Section>

          {/* Reranker */}
          <Section title="Reranker" description="Cross-encoder reranker refines the top-k results after initial retrieval. Higher accuracy, slightly slower.">
            <div className="flex items-center gap-3 mb-3">
              <input
                type="checkbox"
                id="reranker-enabled"
                checked={rerankerEnabled}
                onChange={(e) => setRerankerEnabled(e.target.checked)}
                className="h-4 w-4 accent-indigo-500"
              />
              <label htmlFor="reranker-enabled" className="text-sm text-slate-300 cursor-pointer">
                Enable reranker
              </label>
            </div>
            {rerankerEnabled && (
              <div className="space-y-3">
                <div>
                  <label className="label" htmlFor={rerankerModelId}>Reranker model</label>
                  <select
                    id={rerankerModelId}
                    value={rerankerModel}
                    onChange={(e) => setRerankerModel(e.target.value)}
                    className="input"
                  >
                    <option value="">— select —</option>
                    {rerankersData?.rerankers.map((r) => (
                      <option key={r.model_name} value={r.model_name}>
                        {r.short_name || r.model_name}
                      </option>
                    ))}
                  </select>
                  {(() => {
                    const selected = rerankersData?.rerankers.find((r) => r.model_name === rerankerModel)
                    if (!selected) return null
                    return (
                      <div className="mt-1.5 space-y-1">
                        <p className="text-xs text-slate-500">{selected.description}</p>
                        {selected.recommended_for && (
                          <p className="text-xs text-slate-500">Best for: {selected.recommended_for}</p>
                        )}
                      </div>
                    )
                  })()}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label" htmlFor={recallKId}>Recall-k: {recallK}</label>
                    <input
                      id={recallKId}
                      type="range"
                      min={10}
                      max={200}
                      step={10}
                      value={recallK}
                      onChange={(e) => setRecallK(Number(e.target.value))}
                      className="w-full accent-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="label" htmlFor={minScoreId}>Min reranker score: {minScore.toFixed(2)}</label>
                    <input
                      id={minScoreId}
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={minScore}
                      onChange={(e) => setMinScore(Number(e.target.value))}
                      className="w-full accent-indigo-500"
                    />
                  </div>
                </div>
              </div>
            )}
          </Section>

          {/* Idle memory management */}
          <Section title="Idle Memory Management" description="Release GPU/CPU memory after periods of inactivity. Warm offload moves models to CPU RAM; cold unload fully destroys them.">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label" htmlFor={offloadMinId}>Warm offload after: {offloadMin} min</label>
                <input
                  id={offloadMinId}
                  type="range"
                  min={0}
                  max={120}
                  step={5}
                  value={offloadMin}
                  onChange={(e) => setOffloadMin(Number(e.target.value))}
                  className="w-full accent-indigo-500"
                />
                <p className="text-xs text-slate-600 mt-1">0 = disabled</p>
              </div>
              <div>
                <label className="label" htmlFor={unloadMinId}>Cold unload after: {unloadMin} min</label>
                <input
                  id={unloadMinId}
                  type="range"
                  min={0}
                  max={120}
                  step={5}
                  value={unloadMin}
                  onChange={(e) => setUnloadMin(Number(e.target.value))}
                  className="w-full accent-indigo-500"
                />
                <p className="text-xs text-slate-600 mt-1">0 = disabled</p>
              </div>
            </div>
          </Section>

          {/* Storage info */}
          {settings?._storage_dir && (
            <Section title="Storage" description="">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="font-mono">{settings._storage_dir}</span>
              </div>
            </Section>
          )}

          {/* Save button */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="btn-primary"
            >
              {updateMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )}
              Save Settings
            </button>
            {updateMutation.isSuccess && (
              <span className="flex items-center gap-1 text-green-400 text-sm">
                <CheckCircle size={14} /> Saved
              </span>
            )}
            {updateMutation.isError && (
              <span className="flex items-center gap-1 text-red-400 text-sm">
                <XCircle size={14} />
                {updateMutation.error.message}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Section({ title, description, children }: {
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <div className="card p-4 space-y-3">
      <div>
        <h2 className="text-sm font-medium text-slate-200">{title}</h2>
        {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
      </div>
      {children}
    </div>
  )
}
