import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dashboardApi, authApi, settingsApi } from './api/client'
import { useWebSocket, WSEvent } from './hooks/useWebSocket'
import Dashboard from './components/Dashboard'
import StrategyApprovalView from './components/StrategyApproval'
import AgentComparison from './components/AgentComparison'
import ChatInterface from './components/ChatInterface'
import RiskConfig from './components/RiskConfig'
import { LayoutDashboard, Bot, TrendingUp, MessageSquare, Shield, Wifi, WifiOff, LogIn, Loader2, ChevronDown } from 'lucide-react'

type Tab = 'dashboard' | 'strategies' | 'agents' | 'chat' | 'risk'

function LoginScreen() {
  const { data: authData, isLoading } = useQuery({
    queryKey: ['auth-status'],
    queryFn: () => authApi.getStatus().then(r => r.data),
  })

  const handleLogin = () => {
    window.location.href = '/api/auth/login'
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-sol-dark flex items-center justify-center">
        <Loader2 size={32} className="text-sol-accent animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-sol-dark flex items-center justify-center">
      <div className="bg-sol-card border border-sol-border rounded-2xl p-10 w-full max-w-sm text-center space-y-6">
        <div>
          <p className="text-4xl mb-2">⚡</p>
          <h1 className="text-2xl font-bold text-white">Sol</h1>
          <p className="text-gray-400 text-sm mt-1">AI Trading Orchestrator</p>
        </div>

        {authData?.reason && (
          <p className="text-yellow-400 text-sm bg-yellow-900/20 border border-yellow-700/30 rounded-lg px-4 py-2">
            {authData.reason}
          </p>
        )}

        <button
          onClick={handleLogin}
          className="w-full flex items-center justify-center gap-2 bg-sol-accent hover:bg-sol-accent/80 text-white font-medium py-3 px-6 rounded-xl transition-colors"
        >
          <LogIn size={18} />
          Login with Zerodha
        </button>

        <p className="text-gray-600 text-xs">
          Access is restricted to authorised accounts only.
        </p>
      </div>
    </div>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')
  const [notifications, setNotifications] = useState<string[]>([])
  const queryClient = useQueryClient()

  const { data: authData, isLoading: authLoading } = useQuery({
    queryKey: ['auth-status'],
    queryFn: () => authApi.getStatus().then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: dashboardData } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => dashboardApi.get().then(r => r.data),
    refetchInterval: 15000,
    enabled: authData?.authenticated === true,
  })

  const { connected } = useWebSocket('/api/ws/feed', (event: WSEvent) => {
    if (event.type === 'new_strategy_proposal') {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      setNotifications(n => [`New strategy: ${event.data?.name} (${event.data?.trade_count} trades)`, ...n.slice(0, 4)])
    }
    if (event.type === 'strategy_trade_executed') {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['portfolio'] })
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      setNotifications(n => [`Trade executed: ${event.data?.direction} ${event.data?.symbol}`, ...n.slice(0, 4)])
    }
    if (event.type === 'risk_alert') {
      setNotifications(n => [`⚠ ${event.data?.message}`, ...n.slice(0, 4)])
    }
    if (event.type === 'eod_report') {
      setNotifications(n => ['EOD Report ready — check Chat', ...n.slice(0, 4)])
    }
  })

  // All hooks must be above any early returns (Rules of Hooks)
  const [modeDropdownOpen, setModeDropdownOpen] = useState(false)
  const modeDropdownRef = useRef<HTMLDivElement>(null)

  const { data: modeData, refetch: refetchMode } = useQuery({
    queryKey: ['trading-mode'],
    queryFn: () => settingsApi.getMode().then(r => r.data),
    enabled: authData?.authenticated === true,
  })

  const modeMutation = useMutation({
    mutationFn: (paper: boolean) => settingsApi.setMode(paper).then(r => r.data),
    onSuccess: () => { refetchMode(); queryClient.invalidateQueries({ queryKey: ['dashboard'] }) },
  })

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (modeDropdownRef.current && !modeDropdownRef.current.contains(e.target as Node)) {
        setModeDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Show loading spinner while checking auth
  if (authLoading) {
    return (
      <div className="min-h-screen bg-sol-dark flex items-center justify-center">
        <Loader2 size={32} className="text-sol-accent animate-spin" />
      </div>
    )
  }

  // Show login screen if not authenticated
  if (!authData?.authenticated) {
    return <LoginScreen />
  }

  const mode = modeData?.mode || dashboardData?.mode || 'PAPER'
  const market = dashboardData?.market || {}
  const pending = dashboardData?.activity?.pending_strategies || dashboardData?.activity?.pending_proposals || 0

  const tabs: { id: Tab; label: string; icon: React.ReactNode; badge?: number }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
    { id: 'strategies', label: 'Strategies', icon: <TrendingUp size={18} />, badge: pending },
    { id: 'agents', label: 'Agents', icon: <Bot size={18} /> },
    { id: 'chat', label: 'Chat Sol', icon: <MessageSquare size={18} /> },
    { id: 'risk', label: 'Risk', icon: <Shield size={18} /> },
  ]

  return (
    <div className="min-h-screen bg-sol-dark flex flex-col">
      {/* Top Bar */}
      <header className="border-b border-sol-border bg-sol-card px-4 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-white">⚡ Sol</span>
          {/* Trading mode dropdown */}
          <div className="relative" ref={modeDropdownRef}>
            <button
              onClick={() => setModeDropdownOpen(o => !o)}
              className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded font-mono transition-colors ${
                mode === 'LIVE'
                  ? 'bg-red-900/60 text-red-300 hover:bg-red-900'
                  : 'bg-blue-900/60 text-blue-300 hover:bg-blue-900'
              }`}
            >
              {modeMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : null}
              {mode}
              <ChevronDown size={11} />
            </button>
            {modeDropdownOpen && (
              <div className="absolute left-0 top-full mt-1 w-44 bg-sol-card border border-sol-border rounded-lg shadow-xl z-50 overflow-hidden">
                <div className="px-3 py-2 border-b border-sol-border">
                  <p className="text-xs text-gray-400">Switch trading mode</p>
                </div>
                <button
                  onClick={() => { modeMutation.mutate(true); setModeDropdownOpen(false) }}
                  className={`w-full text-left px-3 py-2.5 text-sm flex items-center gap-2 hover:bg-white/5 transition-colors ${mode === 'PAPER' ? 'text-blue-300' : 'text-gray-300'}`}
                >
                  <span className="w-2 h-2 rounded-full bg-blue-400 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Paper</p>
                    <p className="text-xs text-gray-500">Simulated trades only</p>
                  </div>
                  {mode === 'PAPER' && <span className="ml-auto text-xs text-blue-400">active</span>}
                </button>
                <button
                  onClick={() => {
                    if (confirm('Switch to LIVE mode? Real orders will be placed with real money.')) {
                      modeMutation.mutate(false)
                      setModeDropdownOpen(false)
                    }
                  }}
                  className={`w-full text-left px-3 py-2.5 text-sm flex items-center gap-2 hover:bg-white/5 transition-colors ${mode === 'LIVE' ? 'text-red-300' : 'text-gray-300'}`}
                >
                  <span className="w-2 h-2 rounded-full bg-red-400 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Live</p>
                    <p className="text-xs text-gray-500">Real orders, real money</p>
                  </div>
                  {mode === 'LIVE' && <span className="ml-auto text-xs text-red-400">active</span>}
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 md:gap-4 text-sm">
          <span className={`flex items-center gap-1 ${market.is_open ? 'text-sol-green' : 'text-gray-500'}`}>
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${market.is_open ? 'bg-sol-green animate-pulse' : 'bg-gray-500'}`} />
            <span className="hidden sm:inline">{market.status || 'Loading...'}</span>
          </span>
          <span className="hidden md:inline text-gray-500 font-mono text-xs">{market.time_ist}</span>
          <span className="hidden sm:inline text-gray-500 text-xs truncate max-w-[100px]">{authData.user_name}</span>
          {connected ? <Wifi size={14} className="text-sol-green flex-shrink-0" /> : <WifiOff size={14} className="text-sol-red flex-shrink-0" />}
        </div>
      </header>

      {/* Notifications */}
      {notifications.length > 0 && (
        <div className="bg-yellow-900/20 border-b border-yellow-800/30 px-4 md:px-6 py-2">
          <p className="text-yellow-300 text-xs md:text-sm truncate">{notifications[0]}</p>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar — desktop only */}
        <nav className="hidden md:flex w-52 border-r border-sol-border bg-sol-card p-4 flex-col gap-1 flex-shrink-0">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors relative ${
                activeTab === tab.id
                  ? 'bg-sol-accent/20 text-sol-accent'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              {tab.icon}
              {tab.label}
              {tab.badge ? (
                <span className="ml-auto bg-sol-accent text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                  {tab.badge > 9 ? '9+' : tab.badge}
                </span>
              ) : null}
            </button>
          ))}
        </nav>

        {/* Content */}
        <main className="flex-1 overflow-auto p-3 md:p-6 pb-20 md:pb-6">
          {activeTab === 'dashboard' && <Dashboard data={dashboardData} />}
          {activeTab === 'strategies' && <StrategyApprovalView />}
          {activeTab === 'agents' && <AgentComparison />}
          {activeTab === 'chat' && <ChatInterface />}
          {activeTab === 'risk' && <RiskConfig />}
        </main>
      </div>

      {/* Bottom nav — mobile only */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-sol-card border-t border-sol-border flex z-40">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 relative transition-colors ${
              activeTab === tab.id ? 'text-sol-accent' : 'text-gray-500'
            }`}
          >
            {tab.icon}
            <span className="text-[10px]">{tab.label}</span>
            {tab.badge ? (
              <span className="absolute top-1 right-1/4 bg-sol-accent text-white text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
                {tab.badge > 9 ? '9+' : tab.badge}
              </span>
            ) : null}
          </button>
        ))}
      </nav>
    </div>
  )
}
