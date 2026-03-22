import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { riskApi } from '../api/client'
import { Save, AlertTriangle } from 'lucide-react'

function Slider({ label, value, min, max, step, unit, onChange, danger }: any) {
  return (
    <div>
      <div className="flex justify-between mb-2">
        <label className="text-gray-400 text-sm">{label}</label>
        <span className={`font-mono text-sm font-bold ${danger ? 'text-red-400' : 'text-white'}`}>
          {value}{unit}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full accent-blue-500"
      />
      <div className="flex justify-between text-gray-600 text-xs mt-1">
        <span>{min}{unit}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  )
}

export default function RiskConfig() {
  const queryClient = useQueryClient()
  const [saved, setSaved] = useState(false)

  const { data: config } = useQuery({
    queryKey: ['riskConfig'],
    queryFn: () => riskApi.getConfig().then(r => r.data),
  })

  const { data: report } = useQuery({
    queryKey: ['riskReport'],
    queryFn: () => riskApi.getReport().then(r => r.data),
    refetchInterval: 30000,
  })

  const [form, setForm] = useState({
    max_capital_pct: 2.0,
    daily_loss_limit_pct: 5.0,
    max_open_positions: 5,
    max_position_size_pct: 10.0,
    require_stop_loss: true,
  })

  useEffect(() => {
    if (config) setForm(config)
  }, [config])

  const updateMutation = useMutation({
    mutationFn: (data: object) => riskApi.updateConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['riskConfig'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold text-white">Risk Configuration</h1>

      {/* Live Report */}
      {report && (
        <div className={`border rounded-xl p-5 ${report.trading_halted ? 'border-red-700 bg-red-900/10' : 'border-sol-border bg-sol-card'}`}>
          <div className="flex items-center gap-2 mb-3">
            {report.trading_halted && <AlertTriangle size={18} className="text-red-400" />}
            <h2 className="font-semibold text-white">Current Exposure</h2>
          </div>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <p className="text-gray-500">Capital</p>
              <p className="text-white font-mono">₹{report.capital?.toLocaleString('en-IN')}</p>
            </div>
            <div>
              <p className="text-gray-500">Daily P&L</p>
              <p className={`font-mono ${report.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ₹{report.daily_pnl?.toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Loss Used</p>
              <p className={`font-mono ${report.daily_loss_pct > 3 ? 'text-red-400' : 'text-gray-300'}`}>
                {report.daily_loss_pct?.toFixed(2)}% / {report.daily_loss_limit_pct}%
              </p>
            </div>
            <div>
              <p className="text-gray-500">Open Positions</p>
              <p className="text-white font-mono">{report.open_positions} / {report.max_open_positions}</p>
            </div>
          </div>
          {report.trading_halted && (
            <p className="text-red-400 text-sm mt-3 font-medium">
              ⛔ Trading halted — daily loss limit reached
            </p>
          )}
        </div>
      )}

      {/* Config Form */}
      <div className="bg-sol-card border border-sol-border rounded-xl p-6 space-y-6">
        <Slider
          label="Max Risk Per Trade"
          value={form.max_capital_pct}
          min={0.1} max={10} step={0.1} unit="%"
          onChange={(v: number) => setForm({...form, max_capital_pct: v})}
          danger={form.max_capital_pct > 5}
        />
        <Slider
          label="Daily Loss Limit"
          value={form.daily_loss_limit_pct}
          min={0.5} max={20} step={0.5} unit="%"
          onChange={(v: number) => setForm({...form, daily_loss_limit_pct: v})}
          danger={form.daily_loss_limit_pct > 10}
        />
        <Slider
          label="Max Open Positions"
          value={form.max_open_positions}
          min={1} max={20} step={1} unit=""
          onChange={(v: number) => setForm({...form, max_open_positions: v})}
        />
        <Slider
          label="Max Position Size"
          value={form.max_position_size_pct}
          min={1} max={50} step={1} unit="%"
          onChange={(v: number) => setForm({...form, max_position_size_pct: v})}
          danger={form.max_position_size_pct > 25}
        />

        <div className="flex items-center gap-3 pt-2 border-t border-sol-border">
          <input
            type="checkbox"
            id="requireSL"
            checked={form.require_stop_loss}
            onChange={e => setForm({...form, require_stop_loss: e.target.checked})}
            className="rounded"
          />
          <label htmlFor="requireSL" className="text-gray-300 text-sm">
            Require stop-loss on all proposals (recommended)
          </label>
        </div>

        <button
          onClick={() => updateMutation.mutate(form)}
          className="flex items-center gap-2 bg-sol-accent hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          <Save size={16} />
          {saved ? 'Saved!' : 'Save Risk Config'}
        </button>
      </div>

      <div className="bg-yellow-900/20 border border-yellow-800/40 rounded-xl p-4">
        <p className="text-yellow-400 text-sm font-medium">Important</p>
        <p className="text-gray-400 text-sm mt-1">
          Risk limits are enforced at proposal time AND at execution time. Even if a proposal is approved,
          it will be blocked at execution if market conditions have changed and the risk now exceeds your limits.
        </p>
      </div>
    </div>
  )
}
