import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { strategiesApi } from '../api/client'
import { CheckCircle, XCircle, ChevronDown, ChevronUp, AlertTriangle, Clock, FlaskConical, Loader2 } from 'lucide-react'

const STATUS_COLORS: Record<string, string> = {
  PENDING_APPROVAL: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40',
  ACTIVE: 'bg-blue-900/40 text-blue-300 border-blue-700/40',
  COMPLETED: 'bg-green-900/40 text-green-300 border-green-700/40',
  CANCELLED: 'bg-gray-800 text-gray-400 border-gray-700',
  MAX_LOSS_HIT: 'bg-red-900/40 text-red-300 border-red-700/40',
}

const TRADE_STATUS_COLORS: Record<string, string> = {
  PENDING: 'text-yellow-400',
  EXECUTING: 'text-blue-400',
  EXECUTED: 'text-green-400',
  SKIPPED: 'text-gray-400',
  CANCELLED: 'text-gray-500',
  FAILED: 'text-red-400',
}

function TradeRow({ trade }: { trade: any }) {
  const isLoss = trade.actual_pnl !== null && trade.actual_pnl < 0
  return (
    <div className="flex items-center gap-3 py-2 border-b border-sol-border/30 last:border-0 text-sm">
      <span className="text-gray-500 w-5 text-center font-mono">{trade.sequence}</span>
      <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${trade.direction === 'BUY' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
        {trade.direction}
      </span>
      <span className="text-white font-medium">{trade.symbol}</span>
      <span className="text-gray-500 text-xs">{trade.product_type}</span>
      <span className="text-gray-400 font-mono">×{trade.quantity}</span>
      {trade.stop_loss && <span className="text-red-400 text-xs font-mono">SL ₹{trade.stop_loss}</span>}
      {trade.take_profit && <span className="text-green-400 text-xs font-mono">TP ₹{trade.take_profit}</span>}
      {trade.risk_amount != null && (
        <span className="text-yellow-400 text-xs ml-auto">Risk ₹{trade.risk_amount?.toFixed(0)}</span>
      )}
      <span className={`text-xs ml-2 ${TRADE_STATUS_COLORS[trade.status] || 'text-gray-400'}`}>
        {trade.status}
      </span>
      {trade.actual_pnl != null && (
        <span className={`text-xs font-mono ml-1 ${isLoss ? 'text-red-400' : 'text-green-400'}`}>
          {isLoss ? '' : '+'}₹{trade.actual_pnl?.toFixed(0)}
        </span>
      )}
    </div>
  )
}

function BacktestPanel({ strategyId }: { strategyId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['backtest', strategyId],
    queryFn: () => strategiesApi.backtest(strategyId).then(r => r.data),
    staleTime: Infinity, // don't re-run automatically
  })

  if (isLoading) return (
    <div className="flex items-center gap-2 py-4 text-gray-400 text-sm">
      <Loader2 size={14} className="animate-spin" />
      Running backtest against 90 days of historical data...
    </div>
  )
  if (error) return <p className="text-red-400 text-sm py-2">Backtest failed. Kite data may not be available.</p>
  if (!data) return null

  const overall = data.overall
  const winRate = overall.win_rate_pct
  const winColor = winRate === null ? 'text-gray-400' : winRate >= 60 ? 'text-green-400' : winRate >= 40 ? 'text-yellow-400' : 'text-red-400'

  return (
    <div className="border-t border-sol-border/40 px-4 py-4 bg-black/20 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-gray-300 text-sm font-medium">Backtest Results</p>
        <p className="text-gray-500 text-xs">{data.candles_used} daily candles · {data.duration_days}d hold</p>
      </div>

      {/* Overall */}
      <div className="grid grid-cols-4 gap-2 text-center">
        <div className="bg-gray-800/60 rounded-lg p-2">
          <p className={`text-xl font-bold font-mono ${winColor}`}>{winRate !== null ? `${winRate}%` : '—'}</p>
          <p className="text-gray-500 text-xs mt-0.5">Win Rate</p>
        </div>
        <div className="bg-green-900/20 border border-green-800/30 rounded-lg p-2">
          <p className="text-green-400 text-xl font-bold font-mono">{overall.wins}</p>
          <p className="text-gray-500 text-xs mt-0.5">Wins</p>
        </div>
        <div className="bg-red-900/20 border border-red-800/30 rounded-lg p-2">
          <p className="text-red-400 text-xl font-bold font-mono">{overall.losses}</p>
          <p className="text-gray-500 text-xs mt-0.5">Losses</p>
        </div>
        <div className="bg-gray-800/60 rounded-lg p-2">
          <p className="text-gray-400 text-xl font-bold font-mono">{overall.expired}</p>
          <p className="text-gray-500 text-xs mt-0.5">Expired</p>
        </div>
      </div>

      {/* Per-trade breakdown */}
      <div className="space-y-2">
        {data.trades.map((t: any, i: number) => (
          <div key={i} className="bg-gray-800/40 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${t.direction === 'BUY' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                  {t.direction}
                </span>
                <span className="text-white text-sm font-medium">{t.symbol}</span>
                {t.risk_reward && <span className="text-gray-500 text-xs">R:R {t.risk_reward}</span>}
              </div>
              {t.win_rate_pct !== undefined && t.win_rate_pct !== null ? (
                <span className={`text-sm font-bold font-mono ${t.win_rate_pct >= 60 ? 'text-green-400' : t.win_rate_pct >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {t.win_rate_pct}% win
                </span>
              ) : <span className="text-gray-500 text-xs">{t.error || 'No data'}</span>}
            </div>
            {t.total_scenarios > 0 && (
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span>{t.total_scenarios} scenarios</span>
                <span className="text-green-400">✓ {t.wins} wins</span>
                <span className="text-red-400">✗ {t.losses} losses</span>
                <span>{t.expired} expired</span>
                {t.potential_win_inr && <span className="text-green-400 ml-auto">+₹{t.potential_win_inr}</span>}
                {t.potential_loss_inr && <span className="text-red-400">-₹{t.potential_loss_inr}</span>}
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="text-gray-600 text-xs">{data.data_note}</p>
    </div>
  )
}

function StrategyCard({ strategy, onApprove, onReject }: {
  strategy: any
  onApprove: (id: string, maxLoss: number, note: string) => void
  onReject: (id: string, note: string) => void
}) {
  const [expanded, setExpanded] = useState(strategy.status === 'PENDING_APPROVAL')
  const [maxLoss, setMaxLoss] = useState('')
  const [note, setNote] = useState('')
  const [showBacktest, setShowBacktest] = useState(false)
  const isPending = strategy.status === 'PENDING_APPROVAL'

  const maxLossNum = parseFloat(maxLoss)
  const maxLossValid = maxLossNum > 0 && maxLossNum <= strategy.max_loss_possible
  const lossProgress = strategy.max_loss_approved
    ? Math.min(100, (strategy.actual_loss / strategy.max_loss_approved) * 100)
    : 0

  return (
    <div className={`bg-sol-card border rounded-xl overflow-hidden ${isPending ? 'border-sol-accent/40' : 'border-sol-border'}`}>
      {/* Header */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${STATUS_COLORS[strategy.status] || 'bg-gray-800 text-gray-400'}`}>
                {strategy.status.replace('_', ' ')}
              </span>
              <span className="text-gray-500 text-xs">by {strategy.agent_name}</span>
              <span className="text-gray-600 text-xs">{strategy.duration_days}d · {strategy.trades?.length} trades</span>
            </div>
            <p className="text-white font-bold text-lg mt-1 truncate">{strategy.name}</p>
            <p className="text-gray-400 text-sm mt-0.5 line-clamp-2">{strategy.description}</p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-yellow-400 font-mono text-sm">
              Max risk: ₹{strategy.max_loss_possible?.toFixed(0)}
            </p>
            {strategy.max_loss_approved && (
              <p className="text-gray-400 text-xs">Cap: ₹{strategy.max_loss_approved?.toFixed(0)}</p>
            )}
            {strategy.actual_loss > 0 && (
              <p className="text-red-400 text-xs font-mono">Lost: ₹{strategy.actual_loss?.toFixed(0)}</p>
            )}
          </div>
        </div>

        {/* Loss progress bar for active strategies */}
        {strategy.status === 'ACTIVE' && strategy.max_loss_approved && (
          <div className="mt-3">
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>Loss used</span>
              <span>{lossProgress.toFixed(1)}%</span>
            </div>
            <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${lossProgress > 80 ? 'bg-red-500' : lossProgress > 50 ? 'bg-yellow-500' : 'bg-green-500'}`}
                style={{ width: `${lossProgress}%` }}
              />
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 mt-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-gray-500 text-xs hover:text-gray-300"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {expanded ? 'Hide' : 'Show'} trades & rationale
          </button>
          <button
            onClick={() => setShowBacktest(!showBacktest)}
            className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition-colors ${
              showBacktest
                ? 'bg-purple-900/40 border-purple-700/50 text-purple-300'
                : 'border-sol-border text-gray-500 hover:text-gray-300 hover:border-gray-600'
            }`}
          >
            <FlaskConical size={12} />
            Backtest
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-sol-border/50">
          {/* Rationale */}
          <div className="px-4 py-3 bg-black/20">
            <p className="text-gray-400 text-sm leading-relaxed">{strategy.rationale}</p>
          </div>

          {/* Trades */}
          {strategy.trades?.length > 0 && (
            <div className="px-4 py-3 border-t border-sol-border/30">
              <p className="text-gray-500 text-xs uppercase tracking-wider mb-2">Planned Trades</p>
              {strategy.trades.map((t: any) => <TradeRow key={t.id} trade={t} />)}
            </div>
          )}
        </div>
      )}

      {/* Backtest panel */}
      {showBacktest && <BacktestPanel strategyId={strategy.id} />}

      {/* Approval actions */}
      {isPending && (
        <div className="px-4 pb-4 border-t border-sol-border/50 pt-3 space-y-3">
          <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3 flex gap-2">
            <AlertTriangle size={16} className="text-yellow-400 shrink-0 mt-0.5" />
            <p className="text-yellow-300 text-xs leading-relaxed">
              Set a <strong>maximum loss cap</strong>. All trades execute automatically until this amount is lost.
              Worst case: <strong>₹{strategy.max_loss_possible?.toFixed(0)}</strong> if all stop-losses hit.
            </p>
          </div>

          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-gray-500 text-xs block mb-1">Max loss you allow (₹)</label>
              <input
                type="number"
                value={maxLoss}
                onChange={e => setMaxLoss(e.target.value)}
                placeholder={`e.g. ${Math.round(strategy.max_loss_possible * 0.5)}`}
                className="w-full bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sol-accent font-mono"
                min={1}
                max={strategy.max_loss_possible}
              />
            </div>
            <div className="flex-1">
              <label className="text-gray-500 text-xs block mb-1">Note (optional)</label>
              <input
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="Optional note..."
                className="w-full bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sol-accent"
              />
            </div>
          </div>

          {maxLoss && !maxLossValid && (
            <p className="text-red-400 text-xs">
              {maxLossNum <= 0 ? 'Must be greater than 0' : `Cannot exceed ₹${strategy.max_loss_possible?.toFixed(0)}`}
            </p>
          )}

          <div className="flex gap-2">
            <button
              disabled={!maxLossValid}
              onClick={() => onApprove(strategy.id, maxLossNum, note)}
              className="flex-1 flex items-center justify-center gap-2 bg-green-700 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed text-white py-2 px-4 rounded-lg text-sm font-medium transition-colors"
            >
              <CheckCircle size={16} />
              Approve & Execute
            </button>
            <button
              onClick={() => onReject(strategy.id, note)}
              className="flex-1 flex items-center justify-center gap-2 bg-red-900 hover:bg-red-800 text-white py-2 px-4 rounded-lg text-sm font-medium transition-colors"
            >
              <XCircle size={16} />
              Reject
            </button>
          </div>
        </div>
      )}

      {/* P&L summary for completed/stopped strategies */}
      {(strategy.status === 'COMPLETED' || strategy.status === 'MAX_LOSS_HIT' || strategy.status === 'CANCELLED') && (() => {
        const executedTrades = strategy.trades?.filter((t: any) => t.actual_pnl != null) || []
        if (executedTrades.length === 0) return null
        const totalPnl = executedTrades.reduce((s: number, t: any) => s + (t.actual_pnl ?? 0), 0)
        const wins = executedTrades.filter((t: any) => t.actual_pnl > 0).length
        const losses = executedTrades.filter((t: any) => t.actual_pnl <= 0).length
        return (
          <div className="mx-4 mb-3 rounded-lg overflow-hidden border border-sol-border/50">
            {/* Header */}
            <div className={`px-3 py-2.5 flex items-center justify-between ${totalPnl >= 0 ? 'bg-green-900/20' : 'bg-red-900/20'}`}>
              <p className="text-gray-300 text-sm font-medium">P&L Summary</p>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span><span className="text-green-400 font-bold">{wins}W</span> / <span className="text-red-400 font-bold">{losses}L</span></span>
                <span className={`text-base font-bold font-mono ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toFixed(2)}
                </span>
              </div>
            </div>
            {/* Per-trade rows */}
            <div className="bg-black/20 divide-y divide-sol-border/20">
              {executedTrades.map((t: any) => {
                const pnl = t.actual_pnl ?? 0
                return (
                  <div key={t.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                    <span className={`font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${t.direction === 'BUY' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                      {t.direction}
                    </span>
                    <span className="text-white font-medium">{t.symbol}</span>
                    <span className="text-gray-500">×{t.quantity}</span>
                    {t.entry_price != null && (
                      <span className="text-gray-500 font-mono">@ ₹{Number(t.entry_price).toFixed(2)}</span>
                    )}
                    <span className={`ml-auto font-mono font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                    </span>
                  </div>
                )
              })}
              {/* Total row */}
              {executedTrades.length > 1 && (
                <div className="flex items-center justify-between px-3 py-2 bg-black/30">
                  <span className="text-gray-500 text-xs">{executedTrades.length} trades closed</span>
                  <span className={`font-mono font-bold text-sm ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    Total: {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        )
      })()}

      {/* Status footer for non-pending */}
      {!isPending && (
        <div className="px-4 pb-3 flex items-center gap-3 text-xs text-gray-500">
          {strategy.approved_at && <span>Approved {new Date(strategy.approved_at).toLocaleString()}</span>}
          {strategy.completed_at && <span>Completed {new Date(strategy.completed_at).toLocaleString()}</span>}
          {strategy.user_note && <span className="italic">"{strategy.user_note}"</span>}
        </div>
      )}
    </div>
  )
}

export default function StrategyApprovalView() {
  const [showAll, setShowAll] = useState(false)
  const queryClient = useQueryClient()

  const { data: pending = [] } = useQuery({
    queryKey: ['strategies', 'pending'],
    queryFn: () => strategiesApi.getPending().then(r => r.data),
    refetchInterval: 10000,
  })

  const { data: all = [] } = useQuery({
    queryKey: ['strategies', 'all'],
    queryFn: () => strategiesApi.getAll().then(r => r.data),
    enabled: showAll,
  })

  const approveMutation = useMutation({
    mutationFn: ({ id, maxLoss, note }: { id: string; maxLoss: number; note: string }) =>
      strategiesApi.approve(id, maxLoss, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      strategiesApi.reject(id, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const strategies = showAll ? all : pending

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">
          Strategies
          {pending.length > 0 && (
            <span className="ml-2 text-sm bg-sol-accent text-white px-2 py-0.5 rounded-full">
              {pending.length} pending
            </span>
          )}
        </h1>
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-sm text-gray-400 hover:text-white border border-sol-border px-3 py-1.5 rounded-lg"
        >
          {showAll ? 'Show Pending' : 'Show All'}
        </button>
      </div>

      {strategies.length === 0 && (
        <div className="bg-sol-card border border-sol-border rounded-xl p-12 text-center">
          <Clock size={32} className="text-gray-600 mx-auto mb-3" />
          <p className="text-gray-500">No {showAll ? '' : 'pending '}strategies</p>
          <p className="text-gray-600 text-sm mt-1">Agents propose strategies during market hours every 15 minutes</p>
        </div>
      )}

      <div className="space-y-4">
        {strategies.map((s: any) => (
          <StrategyCard
            key={s.id}
            strategy={s}
            onApprove={(id, maxLoss, note) => approveMutation.mutate({ id, maxLoss, note })}
            onReject={(id, note) => rejectMutation.mutate({ id, note })}
          />
        ))}
      </div>
    </div>
  )
}
