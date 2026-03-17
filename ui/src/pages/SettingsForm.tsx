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
import { Settings, Save, Loader2, CheckCircle, XCircle } from 'lucide-react'
import { api, type SettingsUpdate } from '@/api/client'

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

  // Local form state — initialised from loaded settings
  const [modelName, setModelName] = useState('')
  const [rerankerEnabled, setRerankerEnabled] = useState(false)
  const [rerankerModel, setRerankerModel] = useState('')
  const [recallK, setRecallK] = useState(50)
  const [minScore, setMinScore] = useState(0.0)
  const [offloadMin, setOffloadMin] = useState(15)
  const [unloadMin, setUnloadMin] = useState(30)
  const [initialised, setInitialised] = useState(false)

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
      setInitialised(true)
    }
  }, [settings, initialised])

  const updateMutation = useMutation({
    mutationFn: (update: SettingsUpdate) => api.updateSettings(update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  function handleSave() {
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

  const isLoading = settingsLoading || modelsLoading

  return (
    <div className="p-6 space-y-6 max-w-2xl">
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
                    {m.gpu_default ? ' (GPU)' : ' (CPU)'}
                    {m.embedding_dimension ? ` · ${m.embedding_dimension}d` : ''}
                  </option>
                ))}
              </select>
              {modelsData?.models.find((m) => m.model_name === modelName)?.description && (
                <p className="mt-1.5 text-xs text-slate-500">
                  {modelsData.models.find((m) => m.model_name === modelName)!.description}
                </p>
              )}
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
                  <input
                    id={rerankerModelId}
                    type="text"
                    value={rerankerModel}
                    onChange={(e) => setRerankerModel(e.target.value)}
                    placeholder="cross-encoder/ms-marco-MiniLM-L-6-v2"
                    className="input"
                  />
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
