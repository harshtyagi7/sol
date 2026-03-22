import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tradesApi } from '../api/client'
import { CheckCircle, XCircle, Edit3, ChevronDown, ChevronUp } from 'lucide-react'

function ProposalCard({ proposal, onAction }: { proposal: any; onAction: (action: object) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [note, setNote] = useState('')

  const isGreen = proposal.direction === 'BUY'
  const rr = proposal.stop_loss && proposal.take_profit && proposal.entry_price
    ? ((proposal.take_profit - proposal.entry_price) / (proposal.entry_price - proposal.stop_loss)).toFixed(1)
    : 'N/A'

  return (
    <div className={`bg-sol-card border rounded-xl overflow-hidden ${proposal.status === 'PENDING' ? 'border-sol-accent/40' : 'border-sol-border'}`}>
      <div className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <span className={`text-xs font-bold px-2 py-1 rounded ${isGreen ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
              {proposal.direction}
            </span>
            <div>
              <p className="font-bold text-white text-lg">{proposal.symbol}</p>
              <p className="text-gray-500 text-xs">{proposal.exchange} · {proposal.product_type} · by {proposal.agent_name}</p>
            </div>
          </div>
          <div className="text-right">
            <p className={`text-sm font-mono ${proposal.risk_pct > 1.5 ? 'text-yellow-400' : 'text-gray-400'}`}>
              Risk: {proposal.risk_pct?.toFixed(2)}% · R:R {rr}
            </p>
            <p className="text-gray-500 text-xs">Qty: {proposal.quantity}</p>
          </div>
        </div>

        {/* Prices */}
        <div className="flex gap-4 mt-3 text-sm">
          {proposal.entry_price && <span className="text-gray-400">Entry: <span className="text-white font-mono">₹{proposal.entry_price}</span></span>}
          {proposal.stop_loss && <span className="text-red-400">SL: <span className="font-mono">₹{proposal.stop_loss}</span></span>}
          {proposal.take_profit && <span className="text-green-400">TP: <span className="font-mono">₹{proposal.take_profit}</span></span>}
          {proposal.risk_amount && <span className="text-yellow-400">Risk ₹: <span className="font-mono">₹{proposal.risk_amount?.toFixed(0)}</span></span>}
        </div>

        {/* Expand toggle */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-gray-500 text-xs mt-3 hover:text-gray-300"
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {expanded ? 'Hide' : 'Show'} rationale
        </button>
      </div>

      {expanded && (
        <div className="px-4 pb-3 border-t border-sol-border/50 pt-3">
          <p className="text-gray-400 text-sm leading-relaxed">{proposal.rationale}</p>
          {proposal.risk_violations && (
            <p className="text-yellow-400 text-xs mt-2">⚠ {proposal.risk_violations}</p>
          )}
        </div>
      )}

      {/* Actions for pending proposals */}
      {proposal.status === 'PENDING' && (
        <div className="px-4 pb-4 border-t border-sol-border/50 pt-3">
          <input
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="Optional note..."
            className="w-full bg-gray-800 border border-sol-border rounded-lg px-3 py-2 text-sm text-white mb-3 focus:outline-none focus:border-sol-accent"
          />
          <div className="flex gap-2">
            <button
              onClick={() => onAction({ action: 'approve', note })}
              className="flex-1 flex items-center justify-center gap-2 bg-green-700 hover:bg-green-600 text-white py-2 px-4 rounded-lg text-sm font-medium transition-colors"
            >
              <CheckCircle size={16} /> Approve
            </button>
            <button
              onClick={() => onAction({ action: 'reject', note })}
              className="flex-1 flex items-center justify-center gap-2 bg-red-800 hover:bg-red-700 text-white py-2 px-4 rounded-lg text-sm font-medium transition-colors"
            >
              <XCircle size={16} /> Reject
            </button>
          </div>
        </div>
      )}

      {proposal.status !== 'PENDING' && (
        <div className="px-4 pb-3">
          <span className={`text-xs px-2 py-1 rounded ${
            proposal.status === 'EXECUTED' ? 'bg-green-900/30 text-green-400' :
            proposal.status === 'REJECTED' ? 'bg-red-900/30 text-red-400' :
            'bg-gray-800 text-gray-400'
          }`}>
            {proposal.status}
          </span>
          {proposal.kite_order_id && <span className="text-gray-500 text-xs ml-2">Order: {proposal.kite_order_id}</span>}
        </div>
      )}
    </div>
  )
}

export default function TradeProposals() {
  const [showAll, setShowAll] = useState(false)
  const queryClient = useQueryClient()

  const { data: pending = [] } = useQuery({
    queryKey: ['proposals', 'pending'],
    queryFn: () => tradesApi.getPending().then(r => r.data),
    refetchInterval: 10000,
  })

  const { data: history = [] } = useQuery({
    queryKey: ['proposals', 'history'],
    queryFn: () => tradesApi.getHistory().then(r => r.data),
    enabled: showAll,
  })

  const reviewMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: object }) =>
      tradesApi.review(id, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposals'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const proposals = showAll ? history : pending

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">
          Trade Proposals
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

      {proposals.length === 0 && (
        <div className="bg-sol-card border border-sol-border rounded-xl p-12 text-center">
          <p className="text-gray-500">No {showAll ? '' : 'pending '}proposals</p>
          <p className="text-gray-600 text-sm mt-1">Agents will propose trades during market hours</p>
        </div>
      )}

      <div className="space-y-3">
        {proposals.map((p: any) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            onAction={(action) => reviewMutation.mutate({ id: p.id, action })}
          />
        ))}
      </div>
    </div>
  )
}
