import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Shield, Smartphone, Trash2, Unlock, Loader2, CheckCircle, XCircle, Clock } from 'lucide-react'
import axios from 'axios'

function timeAgo(iso: string | null) {
  if (!iso) return 'Never'
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'Just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function DeviceManager() {
  const qc = useQueryClient()
  const [newPin, setNewPin] = useState('')
  const [confirmPin, setConfirmPin] = useState('')
  const [pinMsg, setPinMsg] = useState('')

  const { data: pinStatus } = useQuery({
    queryKey: ['pin-status'],
    queryFn: () => axios.get('/api/auth/pin/status').then(r => r.data),
  })

  const { data: devices = [], isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: () => axios.get('/api/auth/devices').then(r => r.data),
    refetchInterval: 15000,
  })

  const setPinMutation = useMutation({
    mutationFn: (pin: string) => axios.post('/api/auth/pin/set', { pin }),
    onSuccess: () => {
      setPinMsg('PIN updated successfully')
      setNewPin('')
      setConfirmPin('')
      qc.invalidateQueries({ queryKey: ['pin-status'] })
      setTimeout(() => setPinMsg(''), 3000)
    },
    onError: (e: any) => setPinMsg(e.response?.data?.detail || 'Failed to set PIN'),
  })

  const unblockMutation = useMutation({
    mutationFn: (deviceId: string) => axios.post(`/api/auth/devices/${deviceId}/unblock`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  })

  const removeMutation = useMutation({
    mutationFn: (deviceId: string) => axios.delete(`/api/auth/devices/${deviceId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  })

  const handleSetPin = () => {
    if (newPin !== confirmPin) { setPinMsg('PINs do not match'); return }
    if (!/^\d{4,8}$/.test(newPin)) { setPinMsg('PIN must be 4–8 digits'); return }
    setPinMutation.mutate(newPin)
  }

  const statusIcon = (status: string) => {
    if (status === 'approved') return <CheckCircle size={14} className="text-green-400" />
    if (status === 'blocked') return <XCircle size={14} className="text-red-400" />
    return <Clock size={14} className="text-yellow-400" />
  }

  const statusLabel = (status: string) => {
    if (status === 'approved') return 'text-green-400'
    if (status === 'blocked') return 'text-red-400'
    return 'text-yellow-400'
  }

  return (
    <div className="space-y-6">
      {/* PIN Setup */}
      <div className="bg-sol-card border border-sol-border rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Shield size={16} className="text-sol-accent" />
          <h3 className="text-white font-medium">App PIN</h3>
          <span className={`text-xs px-2 py-0.5 rounded-full ${pinStatus?.pin_set ? 'bg-green-900/30 text-green-400' : 'bg-yellow-900/30 text-yellow-400'}`}>
            {pinStatus?.pin_set ? 'Active' : 'Not set'}
          </span>
        </div>
        <p className="text-gray-400 text-sm">
          {pinStatus?.pin_set
            ? 'Anyone visiting from a new device will need this PIN. Change it below.'
            : 'Set a PIN to restrict access from new devices. Your current device will be auto-approved.'}
        </p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">New PIN (4–8 digits)</label>
            <input
              type="password"
              inputMode="numeric"
              maxLength={8}
              value={newPin}
              onChange={e => setNewPin(e.target.value.replace(/\D/g, ''))}
              placeholder="••••"
              className="w-full bg-sol-dark border border-sol-border rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-sol-accent"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Confirm PIN</label>
            <input
              type="password"
              inputMode="numeric"
              maxLength={8}
              value={confirmPin}
              onChange={e => setConfirmPin(e.target.value.replace(/\D/g, ''))}
              placeholder="••••"
              className="w-full bg-sol-dark border border-sol-border rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-sol-accent"
            />
          </div>
        </div>

        {pinMsg && (
          <p className={`text-sm px-3 py-2 rounded-lg ${pinMsg.includes('success') ? 'bg-green-900/20 text-green-400' : 'bg-red-900/20 text-red-400'}`}>
            {pinMsg}
          </p>
        )}

        <button
          onClick={handleSetPin}
          disabled={!newPin || !confirmPin || setPinMutation.isPending}
          className="flex items-center gap-2 bg-sol-accent hover:bg-sol-accent/80 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          {setPinMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Shield size={14} />}
          {pinStatus?.pin_set ? 'Change PIN' : 'Set PIN'}
        </button>
      </div>

      {/* Device List */}
      <div className="bg-sol-card border border-sol-border rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Smartphone size={16} className="text-sol-accent" />
          <h3 className="text-white font-medium">Known Devices</h3>
          <span className="text-xs text-gray-500">{devices.length} device{devices.length !== 1 ? 's' : ''}</span>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-4">
            <Loader2 size={20} className="text-gray-500 animate-spin" />
          </div>
        ) : devices.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-4">No devices recorded yet</p>
        ) : (
          <div className="space-y-2">
            {devices.map((d: any) => (
              <div key={d.device_id} className="flex items-center justify-between bg-sol-dark rounded-lg px-4 py-3">
                <div className="flex items-center gap-3 min-w-0">
                  {statusIcon(d.status)}
                  <div className="min-w-0">
                    <p className="text-white text-sm font-medium truncate">{d.label}</p>
                    <p className="text-gray-500 text-xs">Last seen {timeAgo(d.last_seen)}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 ml-3 shrink-0">
                  <span className={`text-xs capitalize ${statusLabel(d.status)}`}>{d.status}</span>
                  {d.status === 'blocked' && (
                    <button
                      onClick={() => unblockMutation.mutate(d.device_id)}
                      disabled={unblockMutation.isPending}
                      className="p-1.5 rounded-lg bg-green-900/20 hover:bg-green-900/40 text-green-400 transition-colors"
                      title="Unblock"
                    >
                      <Unlock size={13} />
                    </button>
                  )}
                  <button
                    onClick={() => removeMutation.mutate(d.device_id)}
                    disabled={removeMutation.isPending}
                    className="p-1.5 rounded-lg bg-red-900/20 hover:bg-red-900/40 text-red-400 transition-colors"
                    title="Remove device"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
