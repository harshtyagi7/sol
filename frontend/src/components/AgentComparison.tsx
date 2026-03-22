import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '../api/client'
import { Plus, Play, Pause, Zap } from 'lucide-react'

const PROVIDERS = [
  { id: 'anthropic', label: 'Anthropic (Claude)', models: ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'] },
  { id: 'openai', label: 'OpenAI (GPT)', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'] },
  { id: 'google', label: 'Google (Gemini)', models: ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash'] },
]

function AddAgentModal({ onClose, onAdd }: { onClose: () => void; onAdd: (data: object) => void }) {
  const [form, setForm] = useState({
    name: '', llm_provider: 'anthropic', model_id: 'claude-sonnet-4-6',
    strategy_prompt: '', paper_only: false, virtual_capital: 1000000,
  })

  const selectedProvider = PROVIDERS.find(p => p.id === form.llm_provider)

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-sol-card border border-sol-border rounded-2xl p-6 w-full max-w-lg">
        <h2 className="text-xl font-bold text-white mb-4">Add Trading Agent</h2>
        <div className="space-y-4">
          <div>
            <label className="text-gray-400 text-sm">Agent Name</label>
            <input
              value={form.name}
              onChange={e => setForm({...form, name: e.target.value})}
              placeholder="e.g., alpha-claude"
              className="w-full mt-1 bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-sol-accent"
            />
          </div>
          <div>
            <label className="text-gray-400 text-sm">LLM Provider</label>
            <select
              value={form.llm_provider}
              onChange={e => setForm({...form, llm_provider: e.target.value, model_id: PROVIDERS.find(p => p.id === e.target.value)?.models[0] || ''})}
              className="w-full mt-1 bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-white text-sm focus:outline-none"
            >
              {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-gray-400 text-sm">Model</label>
            <select
              value={form.model_id}
              onChange={e => setForm({...form, model_id: e.target.value})}
              className="w-full mt-1 bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-white text-sm focus:outline-none"
            >
              {selectedProvider?.models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-gray-400 text-sm">Strategy Prompt (optional — uses default if empty)</label>
            <textarea
              value={form.strategy_prompt}
              onChange={e => setForm({...form, strategy_prompt: e.target.value})}
              placeholder="Custom trading strategy instructions..."
              rows={4}
              className="w-full mt-1 bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-white text-sm focus:outline-none resize-none"
            />
          </div>
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="paperOnly"
              checked={form.paper_only}
              onChange={e => setForm({...form, paper_only: e.target.checked})}
              className="rounded"
            />
            <label htmlFor="paperOnly" className="text-gray-400 text-sm">Paper trading only (proposals won't execute live)</label>
          </div>
        </div>
        <div className="flex gap-3 mt-6">
          <button
            onClick={() => onAdd(form)}
            className="flex-1 bg-sol-accent hover:bg-blue-500 text-white py-2 rounded-lg text-sm font-medium transition-colors"
          >
            Add Agent
          </button>
          <button
            onClick={onClose}
            className="flex-1 bg-gray-700 hover:bg-gray-600 text-white py-2 rounded-lg text-sm transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AgentComparison() {
  const [showAdd, setShowAdd] = useState(false)
  const queryClient = useQueryClient()

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list().then(r => r.data),
  })

  const addMutation = useMutation({
    mutationFn: (data: object) => agentsApi.create(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['agents'] }); setShowAdd(false) },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      agentsApi.update(id, { is_active: active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agents'] }),
  })

  const triggerMutation = useMutation({
    mutationFn: (id: string) => agentsApi.trigger(id),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Trading Agents</h1>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 bg-sol-accent hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus size={16} /> Add Agent
        </button>
      </div>

      <p className="text-gray-500 text-sm">
        Each agent independently analyzes the market using its own LLM. Sol reviews all proposals before presenting them to you.
      </p>

      <div className="space-y-3">
        {agents.map((agent: any) => (
          <div key={agent.id} className={`bg-sol-card border rounded-xl p-5 ${agent.is_active ? 'border-sol-border' : 'border-gray-800 opacity-60'}`}>
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h3 className="font-bold text-white">{agent.name}</h3>
                  <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded font-mono">{agent.model_id}</span>
                  {agent.paper_only && <span className="text-xs bg-blue-900/40 text-blue-400 px-2 py-0.5 rounded">paper only</span>}
                  {!agent.is_active && <span className="text-xs bg-gray-800 text-gray-500 px-2 py-0.5 rounded">inactive</span>}
                </div>
                <p className="text-gray-500 text-sm mt-1">
                  Provider: {agent.llm_provider} · Virtual capital: ₹{agent.virtual_capital?.toLocaleString('en-IN')}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => triggerMutation.mutate(agent.id)}
                  disabled={!agent.is_active}
                  title="Trigger analysis now"
                  className="p-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded-lg transition-colors"
                >
                  <Zap size={16} className="text-yellow-400" />
                </button>
                <button
                  onClick={() => toggleMutation.mutate({ id: agent.id, active: !agent.is_active })}
                  className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                >
                  {agent.is_active
                    ? <Pause size={16} className="text-gray-400" />
                    : <Play size={16} className="text-green-400" />
                  }
                </button>
              </div>
            </div>
          </div>
        ))}

        {agents.length === 0 && (
          <div className="bg-sol-card border border-sol-border rounded-xl p-12 text-center">
            <p className="text-gray-500">No agents configured</p>
            <p className="text-gray-600 text-sm mt-1">Add an agent to start receiving trade proposals</p>
          </div>
        )}
      </div>

      {showAdd && (
        <AddAgentModal
          onClose={() => setShowAdd(false)}
          onAdd={data => addMutation.mutate(data)}
        />
      )}
    </div>
  )
}
