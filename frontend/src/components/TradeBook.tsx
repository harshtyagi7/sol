import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { portfolioApi } from '../api/client'
import { X, RefreshCw, TrendingUp, TrendingDown, Clock, ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react'
import { calculateCharges } from '../utils/charges'

function duration(openedAt: string, closedAt: string | null): string {
  const start = new Date(openedAt).getTime()
  const end = closedAt ? new Date(closedAt).getTime() : Date.now()
  const mins = Math.floor((end - start) / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const rem = mins % 60
  if (hrs < 24) return rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

/**
 * SQUAREDOFF = Zerodha's RMS auto-squared the position (₹59 charge).
 * CLOSED = Sol placed the close order at 3:20 PM (no extra charge).
 */
function isZerodhaSqOff(trade: any): boolean {
  return trade.status === 'SQUAREDOFF'
}

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  SL_HIT:     { label: 'SL Hit',       color: 'text-red-400 bg-red-900/30' },
  TP_HIT:     { label: 'TP Hit',       color: 'text-green-400 bg-green-900/30' },
  SQUAREDOFF: { label: 'Auto Sq-Off',  color: 'text-yellow-400 bg-yellow-900/30' },
  CLOSED:     { label: 'Squared Off',  color: 'text-blue-400 bg-blue-900/30' },
  EXPIRED:    { label: 'Expired',      color: 'text-gray-400 bg-gray-800' },
}

function DirectionBadge({ direction }: { direction: string }) {
  return (
    <span className={`text-xs font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${
      direction === 'BUY' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
    }`}>
      {direction}
    </span>
  )
}

function ChargesDetail({ trade }: { trade: any }) {
  const autoSqOff = isZerodhaSqOff(trade)
  const charges = calculateCharges(
    trade.avg_price,
    trade.close_price ?? trade.avg_price,
    trade.quantity,
    trade.direction,
    trade.product_type ?? 'MIS',
    trade.exchange ?? 'NSE',
    autoSqOff,
  )
  const grossPnl = trade.realized_pnl ?? 0
  const netPnl = grossPnl - charges.total

  return (
    <div className="mt-3 pt-3 border-t border-sol-border/40 text-xs space-y-1.5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-gray-400">
        <div className="flex justify-between">
          <span>Brokerage</span>
          <span className="font-mono text-gray-300">₹{charges.brokerage.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span>STT</span>
          <span className="font-mono text-gray-300">₹{charges.stt.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span>Exchange charges</span>
          <span className="font-mono text-gray-300">₹{charges.exchangeCharges.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span>Stamp duty</span>
          <span className="font-mono text-gray-300">₹{charges.stampDuty.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span>SEBI charges</span>
          <span className="font-mono text-gray-300">₹{charges.sebi.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span>GST (18%)</span>
          <span className="font-mono text-gray-300">₹{charges.gst.toFixed(2)}</span>
        </div>
        {charges.autoSquareoffCharge > 0 && (
          <div className="flex justify-between col-span-2 text-yellow-400">
            <span className="flex items-center gap-1"><AlertTriangle size={10} /> Auto sq-off penalty (Zerodha)</span>
            <span className="font-mono">₹{charges.autoSquareoffCharge.toFixed(2)}</span>
          </div>
        )}
      </div>
      <div className="flex justify-between items-center pt-1 border-t border-sol-border/30">
        <span className="text-gray-400">Total charges</span>
        <span className="font-mono text-orange-400">−₹{charges.total.toFixed(2)}</span>
      </div>
      <div className="flex justify-between items-center font-medium">
        <span className="text-gray-300">Gross P&L</span>
        <span className={`font-mono ${grossPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {grossPnl >= 0 ? '+' : ''}₹{grossPnl.toFixed(2)}
        </span>
      </div>
      <div className="flex justify-between items-center font-bold">
        <span className="text-white">Net P&L (after charges)</span>
        <span className={`font-mono text-base ${netPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {netPnl >= 0 ? '+' : ''}₹{netPnl.toFixed(2)}
        </span>
      </div>
    </div>
  )
}

function TradeRow({ t }: { t: any }) {
  const [expanded, setExpanded] = useState(false)
  const pnl = t.realized_pnl
  const statusInfo = STATUS_LABEL[t.status] || { label: t.status, color: 'text-gray-400 bg-gray-800' }
  const autoSqOff = isZerodhaSqOff(t)

  const charges = t.close_price != null ? calculateCharges(
    t.avg_price, t.close_price, t.quantity, t.direction,
    t.product_type ?? 'MIS', t.exchange ?? 'NSE', autoSqOff,
  ) : null
  const netPnl = pnl != null && charges ? pnl - charges.total : null

  return (
    <div className="px-4 py-3">
      {/* Mobile layout */}
      <div className="md:hidden space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <DirectionBadge direction={t.direction} />
            <span className="text-white font-medium">{t.symbol}</span>
            <span className="text-gray-500 text-xs">{t.exchange}</span>
            {t.is_virtual && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-900/40 text-blue-400">PAPER</span>}
            {autoSqOff && <span className="text-[10px] px-1 py-0.5 rounded bg-yellow-900/40 text-yellow-400">AUTO SQ</span>}
          </div>
          <div className="text-right">
            {netPnl != null ? (
              <>
                <div className={`font-mono font-bold ${netPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {netPnl >= 0 ? '+' : ''}₹{netPnl.toFixed(2)}
                </div>
                <div className="text-gray-600 text-[10px] font-mono">net</div>
              </>
            ) : <span className="text-gray-600 font-mono">—</span>}
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>×{t.quantity}</span>
          <span>Entry ₹{t.avg_price.toFixed(2)}</span>
          {t.close_price && <span>Exit ₹{t.close_price.toFixed(2)}</span>}
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusInfo.color}`}>{statusInfo.label}</span>
          <span className="flex items-center gap-0.5 text-gray-600 ml-auto"><Clock size={10} />{duration(t.opened_at, t.closed_at)}</span>
        </div>
        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-600">by {t.agent_name} · {t.closed_at ? new Date(t.closed_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}</div>
          {charges && (
            <button onClick={() => setExpanded(v => !v)} className="text-gray-500 hover:text-gray-300 flex items-center gap-0.5 text-xs">
              Charges {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          )}
        </div>
        {expanded && charges && <ChargesDetail trade={t} />}
      </div>

      {/* Desktop layout */}
      <div className="hidden md:block">
        <div className="grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto_auto_auto] gap-3 items-center text-sm">
          <DirectionBadge direction={t.direction} />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-medium">{t.symbol}</span>
              <span className="text-gray-500 text-xs">{t.exchange}</span>
              <span className="text-gray-600 text-xs">{t.product_type}</span>
              {t.is_virtual && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-900/40 text-blue-400">PAPER</span>}
              {autoSqOff && <span className="text-[10px] px-1 py-0.5 rounded bg-yellow-900/40 text-yellow-400">AUTO SQ</span>}
            </div>
            <div className="text-xs text-gray-600 mt-0.5">
              {t.agent_name} · {t.closed_at ? new Date(t.closed_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}
            </div>
          </div>
          <span className="text-gray-300 font-mono text-right">{t.quantity}</span>
          <span className="text-gray-300 font-mono text-right">₹{t.avg_price.toFixed(2)}</span>
          <span className="text-gray-300 font-mono text-right">{t.close_price ? `₹${t.close_price.toFixed(2)}` : '—'}</span>
          {/* Gross P&L */}
          {pnl != null ? (
            <span className={`font-mono text-right text-xs ${pnl >= 0 ? 'text-green-700' : 'text-red-700'}`}>
              {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
            </span>
          ) : <span className="text-gray-600 font-mono text-right">—</span>}
          {/* Net P&L */}
          {netPnl != null ? (
            <span className={`font-mono font-bold text-right ${netPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {netPnl >= 0 ? '+' : ''}₹{netPnl.toFixed(2)}
            </span>
          ) : <span className="text-gray-600 font-mono text-right">—</span>}
          <span className="text-gray-500 font-mono text-right text-xs">{duration(t.opened_at, t.closed_at)}</span>
          <div className="flex items-center gap-2 justify-end">
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${statusInfo.color}`}>{statusInfo.label}</span>
            {charges && (
              <button onClick={() => setExpanded(v => !v)} className="text-gray-600 hover:text-gray-300">
                {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
            )}
          </div>
        </div>
        {expanded && charges && <ChargesDetail trade={t} />}
      </div>
    </div>
  )
}

function OpenPositions() {
  const queryClient = useQueryClient()
  const { data: positions = [], isLoading, refetch } = useQuery({
    queryKey: ['positions'],
    queryFn: () => portfolioApi.getPositions().then(r => r.data),
    refetchInterval: 10000,
  })

  const closeMutation = useMutation({
    mutationFn: (id: string) => portfolioApi.closePosition(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['trades'] })
    },
  })

  if (isLoading) return <div className="text-gray-500 text-sm py-8 text-center">Loading...</div>

  if (positions.length === 0) {
    return (
      <div className="text-center py-16">
        <TrendingUp size={32} className="text-gray-700 mx-auto mb-3" />
        <p className="text-gray-500">No open positions</p>
        <p className="text-gray-600 text-sm mt-1">Positions will appear here when strategies execute trades</p>
      </div>
    )
  }

  const totalUnrealized = positions.reduce((s: number, p: any) => s + (p.unrealized_pnl ?? 0), 0)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between bg-sol-card border border-sol-border rounded-lg px-4 py-2.5">
        <span className="text-gray-400 text-sm">{positions.length} open position{positions.length !== 1 ? 's' : ''}</span>
        <div className="flex items-center gap-2">
          <span className="text-gray-500 text-xs">Unrealized P&L</span>
          <span className={`font-mono font-bold ${totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totalUnrealized >= 0 ? '+' : ''}₹{totalUnrealized.toFixed(2)}
          </span>
          <button onClick={() => refetch()} className="text-gray-600 hover:text-gray-300 ml-1">
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      {positions.map((p: any) => {
        const pnl = p.unrealized_pnl ?? 0
        const pnlPct = p.avg_price > 0 ? (pnl / (p.avg_price * p.quantity)) * 100 : 0
        return (
          <div key={p.id} className="bg-sol-card border border-sol-border rounded-xl p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <DirectionBadge direction={p.direction} />
                <span className="text-white font-bold">{p.symbol}</span>
                <span className="text-gray-500 text-xs">{p.exchange}</span>
                <span className="text-gray-600 text-xs">{p.product_type}</span>
                {p.is_virtual && <span className="text-xs px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-400 border border-blue-800/40">PAPER</span>}
              </div>
              <div className="text-right flex-shrink-0">
                <p className={`font-mono font-bold text-lg ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                </p>
                <p className={`text-xs font-mono ${pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                </p>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>
                <p className="text-gray-500 text-xs">Qty</p>
                <p className="text-white font-mono">{p.quantity}</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Avg Price</p>
                <p className="text-white font-mono">₹{Number(p.avg_price).toFixed(2)}</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">LTP</p>
                <p className="text-white font-mono">{p.current_price ? `₹${Number(p.current_price).toFixed(2)}` : '—'}</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Held</p>
                <p className="text-gray-300 font-mono">{duration(p.opened_at, null)}</p>
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-4 text-xs">
                {p.stop_loss && (
                  <span className="text-red-400 font-mono">SL ₹{Number(p.stop_loss).toFixed(2)}</span>
                )}
                {p.take_profit && (
                  <span className="text-green-400 font-mono">TP ₹{Number(p.take_profit).toFixed(2)}</span>
                )}
                <span className="text-gray-600">by {p.agent_name}</span>
              </div>
              <button
                onClick={() => {
                  if (confirm(`Close ${p.direction} ${p.quantity} ${p.symbol} at market?`)) {
                    closeMutation.mutate(p.id)
                  }
                }}
                disabled={closeMutation.isPending}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-red-900/40 text-red-400 hover:bg-red-900/70 border border-red-800/40 disabled:opacity-40 transition-colors"
              >
                <X size={12} />
                Close
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ClosedTrades() {
  const { data: trades = [], isLoading } = useQuery({
    queryKey: ['trades'],
    queryFn: () => portfolioApi.getTrades().then(r => r.data),
    staleTime: 30000,
  })

  if (isLoading) return <div className="text-gray-500 text-sm py-8 text-center">Loading...</div>

  if (trades.length === 0) {
    return (
      <div className="text-center py-16">
        <TrendingDown size={32} className="text-gray-700 mx-auto mb-3" />
        <p className="text-gray-500">No closed trades yet</p>
      </div>
    )
  }

  const totalGrossPnl = trades.reduce((s: number, t: any) => s + (t.realized_pnl ?? 0), 0)
  const totalCharges = trades.reduce((s: number, t: any) => {
    if (t.close_price == null) return s
    return s + calculateCharges(t.avg_price, t.close_price, t.quantity, t.direction,
      t.product_type ?? 'MIS', t.exchange ?? 'NSE', isZerodhaSqOff(t)).total
  }, 0)
  const totalNetPnl = totalGrossPnl - totalCharges
  const wins = trades.filter((t: any) => (t.realized_pnl ?? 0) > 0).length

  return (
    <div className="space-y-3">
      {/* Summary bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-sol-card border border-sol-border rounded-lg px-4 py-2.5">
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-400">{trades.length} trades</span>
          <span className="text-green-400 text-xs">{wins}W</span>
          <span className="text-red-400 text-xs">{trades.length - wins}L</span>
          {trades.length > 0 && (
            <span className="text-gray-500 text-xs">{Math.round(wins / trades.length * 100)}% win rate</span>
          )}
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="text-right">
            <span className="text-gray-500 text-xs mr-2">Gross P&L</span>
            <span className={`font-mono ${totalGrossPnl >= 0 ? 'text-green-700' : 'text-red-700'}`}>
              {totalGrossPnl >= 0 ? '+' : ''}₹{totalGrossPnl.toFixed(2)}
            </span>
          </div>
          <div className="text-right">
            <span className="text-gray-500 text-xs mr-2">Charges</span>
            <span className="font-mono text-orange-400">−₹{totalCharges.toFixed(2)}</span>
          </div>
          <div className="text-right">
            <span className="text-gray-500 text-xs mr-2">Net P&L</span>
            <span className={`font-mono font-bold ${totalNetPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {totalNetPnl >= 0 ? '+' : ''}₹{totalNetPnl.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Trade rows */}
      <div className="bg-sol-card border border-sol-border rounded-xl overflow-hidden">
        <div className="hidden md:grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto_auto_auto] gap-3 px-4 py-2 border-b border-sol-border text-xs text-gray-500 uppercase tracking-wider">
          <span>Dir</span>
          <span>Symbol</span>
          <span className="text-right">Qty</span>
          <span className="text-right">Entry</span>
          <span className="text-right">Exit</span>
          <span className="text-right">Gross P&L</span>
          <span className="text-right">Net P&L</span>
          <span className="text-right">Duration</span>
          <span className="text-right">Status</span>
        </div>
        <div className="divide-y divide-sol-border/30">
          {trades.map((t: any) => <TradeRow key={t.id} t={t} />)}
        </div>
      </div>
    </div>
  )
}

export default function TradeBook() {
  const [tab, setTab] = useState<'open' | 'closed'>('open')

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Trade Book</h1>
        <div className="flex bg-sol-card border border-sol-border rounded-lg p-0.5">
          <button
            onClick={() => setTab('open')}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              tab === 'open' ? 'bg-sol-accent/20 text-sol-accent' : 'text-gray-400 hover:text-white'
            }`}
          >
            Open
          </button>
          <button
            onClick={() => setTab('closed')}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              tab === 'closed' ? 'bg-sol-accent/20 text-sol-accent' : 'text-gray-400 hover:text-white'
            }`}
          >
            Closed
          </button>
        </div>
      </div>

      {tab === 'open' ? <OpenPositions /> : <ClosedTrades />}
    </div>
  )
}
