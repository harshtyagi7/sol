import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { riskApi } from '../api/client'
import { Save, AlertTriangle } from 'lucide-react'
import DeviceManager from './DeviceManager'

function RupeeInput({
  label,
  sublabel,
  value,
  onChange,
  min,
  max,
  step,
  danger,
  capitalRs,
}: {
  label: string
  sublabel: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  step: number
  danger?: boolean
  capitalRs?: number
}) {
  const absValue = capitalRs ? Math.round((value / 100) * capitalRs) : null

  return (
    <div>
      <div className="flex justify-between mb-1">
        <div>
          <p className="text-white text-sm font-medium">{label}</p>
          <p className="text-gray-500 text-xs">{sublabel}</p>
        </div>
        <div className="text-right">
          <span className={`font-mono text-lg font-bold ${danger ? 'text-red-400' : 'text-white'}`}>
            {value}%
          </span>
          {absValue !== null && (
            <p className="text-gray-400 text-xs font-mono">≈ ₹{absValue.toLocaleString('en-IN')}</p>
          )}
        </div>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full accent-blue-500 mt-2"
      />
      <div className="flex justify-between text-gray-600 text-xs mt-1">
        <span>{min}%</span>
        <span>{max}%</span>
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

  const [maxCapitalPct, setMaxCapitalPct] = useState(2.0)
  const [dailyLossPct, setDailyLossPct] = useState(5.0)

  useEffect(() => {
    if (config) {
      setMaxCapitalPct(config.max_capital_pct)
      setDailyLossPct(config.daily_loss_limit_pct)
    }
  }, [config])

  const updateMutation = useMutation({
    mutationFn: () =>
      riskApi.updateConfig({
        // Only update the two user-controlled fields; preserve everything else
        max_capital_pct: maxCapitalPct,
        daily_loss_limit_pct: dailyLossPct,
        max_open_positions: config?.max_open_positions ?? 5,
        max_position_size_pct: config?.max_position_size_pct ?? 10,
        require_stop_loss: config?.require_stop_loss ?? true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['riskConfig'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  const capital = report?.capital ?? null

  return (
    <div className="space-y-6 max-w-xl">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      {/* Live status */}
      {report && (
        <div className={`border rounded-xl p-5 ${report.trading_halted ? 'border-red-700 bg-red-900/10' : 'border-sol-border bg-sol-card'}`}>
          <div className="flex items-center gap-2 mb-3">
            {report.trading_halted && <AlertTriangle size={16} className="text-red-400" />}
            <h2 className="text-sm font-semibold text-gray-400">Today</h2>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-gray-500 text-xs">Capital</p>
              <p className="text-white font-mono">₹{report.capital?.toLocaleString('en-IN')}</p>
            </div>
            <div>
              <p className="text-gray-500 text-xs">Daily P&L</p>
              <p className={`font-mono ${report.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ₹{report.daily_pnl?.toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-gray-500 text-xs">Loss used today</p>
              <p className={`font-mono ${report.daily_loss_pct > 3 ? 'text-red-400' : 'text-gray-300'}`}>
                {report.daily_loss_pct?.toFixed(2)}% of {dailyLossPct}% limit
              </p>
            </div>
            <div>
              <p className="text-gray-500 text-xs">Open positions</p>
              <p className="text-white font-mono">{report.open_positions}</p>
            </div>
          </div>
          {report.trading_halted && (
            <p className="text-red-400 text-sm mt-3 font-medium">
              ⛔ Trading halted — daily loss limit reached
            </p>
          )}
        </div>
      )}

      {/* The two settings */}
      <div className="bg-sol-card border border-sol-border rounded-xl p-6 space-y-8">
        <RupeeInput
          label="Capital agents can use per trade"
          sublabel="Maximum capital deployed per trade entry"
          value={maxCapitalPct}
          onChange={setMaxCapitalPct}
          min={0.5}
          max={100}
          step={0.5}
          capitalRs={capital ?? undefined}
        />
        <RupeeInput
          label="Max loss per day"
          sublabel="Trading halts automatically if this is exceeded"
          value={dailyLossPct}
          onChange={setDailyLossPct}
          min={0.5}
          max={10}
          step={0.5}
          danger={dailyLossPct > 5}
          capitalRs={capital ?? undefined}
        />

        <button
          onClick={() => updateMutation.mutate()}
          disabled={updateMutation.isPending}
          className="flex items-center gap-2 bg-sol-accent hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
        >
          <Save size={16} />
          {saved ? 'Saved!' : 'Save'}
        </button>
      </div>

      <DeviceManager />
    </div>
  )
}
