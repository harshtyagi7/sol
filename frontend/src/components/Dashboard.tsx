import { useQuery } from '@tanstack/react-query'
import { portfolioApi } from '../api/client'
import { TrendingUp, TrendingDown, DollarSign, Activity, AlertTriangle } from 'lucide-react'

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

export default function Dashboard({ data }: Props) {
  const portfolio = data?.portfolio || {}
  const risk = data?.risk || {}
  const agents = data?.agents || []

  const pnl = portfolio.total_pnl_today || 0
  const pnlColor = pnl >= 0 ? 'green' : 'red'

  const riskUsed = risk.daily_loss_pct || 0
  const riskLimit = risk.daily_loss_limit_pct || 5
  const riskPct = Math.min((riskUsed / riskLimit) * 100, 100)

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Dashboard</h1>

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
