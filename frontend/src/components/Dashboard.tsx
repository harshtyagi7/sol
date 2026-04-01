import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { portfolioApi, agentsApi } from '../api/client'
import { TrendingUp, TrendingDown, DollarSign, Activity, AlertTriangle, X, Play, Loader2, RefreshCw } from 'lucide-react'

interface Props { data?: any }

function StatCard({ title, value, sub, color = 'white', icon }: any) {
  return (
    <div className="bg-sol-card border border-sol-border rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-gray-400 text-sm">{title}</p>
          <p className={`text-2xl font-bold mt-1 text-${color}-400`}>{value}</p>
          {sub && <p className="text-gray-500 text-xs mt-1">{sub}</p>}
        </div>
        <div className="text-gray-600">{icon}</div>
      </div>
    </div>
  )
}

function OpenPositions() {
  const queryClient = useQueryClient()
  const { data: positions = [] } = useQuery({
    queryKey: ['positions'],
    queryFn: () => portfolioApi.getPositions().then(r => r.data),
    refetchInterval: 10_000,
  })

  const closeMutation = useMutation({
    mutationFn: (id: string) => portfolioApi.closePosition(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['positions'] }),
  })

  if (positions.length === 0) return null

  return (
    <div className="bg-sol-card border border-sol-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-white">Open Positions</h2>
        <span className="text-xs text-gray-500">auto-refreshes every 10s</span>
      </div>
      <div className="space-y-2">
        {positions.map((p: any) => {
          const pnl = p.unrealized_pnl ?? 0
          const pnlPct = p.avg_price ? ((p.current_price - p.avg_price) / p.avg_price * 100) * (p.direction === 'BUY' ? 1 : -1) : 0
          return (
            <div key={p.id} className="flex items-center gap-2 md:gap-3 bg-black/20 rounded-lg px-3 py-2.5 text-sm flex-wrap">
              <span className={`text-xs font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${p.direction === 'BUY' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                {p.direction}
              </span>
              <span className="text-white font-medium">{p.symbol}</span>
              <span className="text-gray-500 text-xs">×{p.quantity}</span>
              {p.is_virtual && <span className="text-xs text-blue-400 bg-blue-900/30 px-1.5 py-0.5 rounded">PAPER</span>}
              <span className="text-gray-400 font-mono text-xs">avg ₹{Number(p.avg_price).toFixed(2)}</span>
              {p.current_price && (
                <span className="text-gray-300 font-mono text-xs">ltp ₹{Number(p.current_price).toFixed(2)}</span>
              )}
              {p.stop_loss && <span className="text-red-400 text-xs font-mono hidden sm:inline">SL ₹{Number(p.stop_loss).toFixed(2)}</span>}
              <span className={`font-mono text-sm font-bold ml-auto ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                <span className="text-xs font-normal ml-1 opacity-70">({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%)</span>
              </span>
              <button
                onClick={() => { if (confirm(`Close ${p.symbol} position?`)) closeMutation.mutate(p.id) }}
                className="text-gray-600 hover:text-red-400 transition-colors flex-shrink-0"
                title="Close position"
              >
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>

      {/* Unrealized total */}
      {positions.length > 1 && (() => {
        const total = positions.reduce((s: number, p: any) => s + (p.unrealized_pnl ?? 0), 0)
        return (
          <div className={`flex justify-end mt-3 pt-2 border-t border-sol-border/40 text-sm font-mono font-bold ${total >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            Total unrealized: {total >= 0 ? '+' : ''}₹{total.toFixed(2)}
          </div>
        )
      })()}
    </div>
  )
}

export default function Dashboard({ data }: Props) {
  const queryClient = useQueryClient()
  const [cycleStatus, setCycleStatus] = useState<string | null>(null)
  const [syncStatus, setSyncStatus] = useState<string | null>(null)

  const portfolio = data?.portfolio || {}
  const risk = data?.risk || {}
  const agents = data?.agents || []

  const pnl = portfolio.total_pnl_today || 0
  const pnlColor = pnl >= 0 ? 'green' : 'red'

  const riskUsed = risk.daily_loss_pct || 0
  const riskLimit = risk.daily_loss_limit_pct || 5
  const riskPct = Math.min((riskUsed / riskLimit) * 100, 100)

  const runCycle = useMutation({
    mutationFn: () => agentsApi.triggerCycle(),
    onMutate: () => setCycleStatus('running'),
    onSuccess: () => {
      setCycleStatus('done')
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setTimeout(() => setCycleStatus(null), 4000)
    },
    onError: () => {
      setCycleStatus('error')
      setTimeout(() => setCycleStatus(null), 4000)
    },
  })

  const syncKite = useMutation({
    mutationFn: () => portfolioApi.syncFromKite(),
    onMutate: () => setSyncStatus('syncing'),
    onSuccess: (res) => {
      const n = res.data?.synced ?? 0
      setSyncStatus(n > 0 ? `synced ${n}` : 'up to date')
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setTimeout(() => setSyncStatus(null), 5000)
    },
    onError: () => {
      setSyncStatus('error')
      setTimeout(() => setSyncStatus(null), 4000)
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => syncKite.mutate()}
            disabled={syncKite.isPending}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border border-sol-border bg-sol-card text-gray-300 hover:text-white hover:border-gray-500 transition-colors disabled:opacity-50"
            title="Sync positions from Kite"
          >
            {syncKite.isPending
              ? <><Loader2 size={13} className="animate-spin" /> Syncing…</>
              : syncStatus && syncStatus !== 'error'
              ? <><RefreshCw size={13} className="text-green-400" /> {syncStatus}</>
              : syncStatus === 'error'
              ? <><RefreshCw size={13} className="text-red-400" /> Error</>
              : <><RefreshCw size={13} /> Sync Kite</>
            }
          </button>
          <button
            onClick={() => runCycle.mutate()}
            disabled={runCycle.isPending}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border border-sol-border bg-sol-card text-gray-300 hover:text-white hover:border-gray-500 transition-colors disabled:opacity-50"
          >
            {runCycle.isPending
              ? <><Loader2 size={13} className="animate-spin" /> Running…</>
              : cycleStatus === 'done'
              ? <><Play size={13} className="text-green-400" /> Cycle done!</>
              : cycleStatus === 'error'
              ? <><Play size={13} className="text-red-400" /> Error</>
              : <><Play size={13} /> Run Cycle</>
            }
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <StatCard
          title="Available Capital"
          value={`₹${(portfolio.available_capital || 0).toLocaleString('en-IN')}`}
          icon={<DollarSign size={20} />}
        />
        <StatCard
          title="Today's P&L"
          value={`${pnl >= 0 ? '+' : ''}₹${pnl.toLocaleString('en-IN')}`}
          sub={`Realized: ₹${(portfolio.realized_pnl_today || 0).toFixed(2)} | Unrealized: ₹${(portfolio.unrealized_pnl || 0).toFixed(2)}`}
          color={pnlColor}
          icon={pnl >= 0 ? <TrendingUp size={20} /> : <TrendingDown size={20} />}
        />
        <StatCard
          title="Open Positions"
          value={portfolio.open_positions || 0}
          sub={`Max: ${risk.max_open_positions || 5}`}
          icon={<Activity size={20} />}
        />
        <StatCard
          title="Pending Proposals"
          value={data?.activity?.pending_proposals || 0}
          icon={<AlertTriangle size={20} />}
        />
      </div>

      {/* Risk Meter */}
      <div className="bg-sol-card border border-sol-border rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-white">Daily Loss Limit</h2>
          <span className={`text-sm font-mono ${risk.trading_halted ? 'text-red-400' : 'text-gray-400'}`}>
            {risk.trading_halted ? '⛔ TRADING HALTED' : `${riskUsed.toFixed(2)}% / ${riskLimit}%`}
          </span>
        </div>
        <div className="h-3 bg-gray-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              riskPct > 80 ? 'bg-red-500' : riskPct > 50 ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${riskPct}%` }}
          />
        </div>
        <p className="text-gray-500 text-xs mt-2">
          Daily P&L: ₹{(risk.daily_pnl || 0).toFixed(2)} | Capital: ₹{(risk.capital || 0).toLocaleString('en-IN')}
        </p>
      </div>

      {/* Open Positions */}
      <OpenPositions />

      {/* Agent Performance */}
      {agents.length > 0 && (
        <div className="bg-sol-card border border-sol-border rounded-xl p-5">
          <h2 className="font-semibold text-white mb-4">Agent Performance</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-left border-b border-sol-border">
                  <th className="pb-2">Agent</th>
                  <th className="pb-2">Model</th>
                  <th className="pb-2 text-right">Virtual Capital</th>
                  <th className="pb-2 text-right">P&L</th>
                  <th className="pb-2 text-right">P&L %</th>
                  <th className="pb-2 text-right">Win Rate</th>
                  <th className="pb-2 text-right">Trades</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a: any) => {
                  const pnl = a.total_pnl || 0
                  return (
                    <tr key={a.agent_id} className="border-b border-sol-border/50 text-gray-300">
                      <td className="py-2 font-medium text-white">{a.agent_name}</td>
                      <td className="py-2 text-gray-500 font-mono text-xs">{a.model_id}</td>
                      <td className="py-2 text-right font-mono">₹{a.virtual_capital_current?.toLocaleString('en-IN')}</td>
                      <td className={`py-2 text-right font-mono ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                      </td>
                      <td className={`py-2 text-right font-mono ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {a.total_pnl_pct?.toFixed(2)}%
                      </td>
                      <td className="py-2 text-right font-mono">{a.win_rate?.toFixed(1)}%</td>
                      <td className="py-2 text-right font-mono">{a.closed_trades}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
