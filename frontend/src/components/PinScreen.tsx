import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Lock, ShieldOff, Loader2 } from 'lucide-react'
import axios from 'axios'

interface Props {
  deviceId: string
  deviceLabel: string
  blocked: boolean
  onApproved: () => void
}

export default function PinScreen({ deviceId, deviceLabel, blocked, onApproved }: Props) {
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')

  const verifyMutation = useMutation({
    mutationFn: () =>
      axios.post('/api/auth/device/verify', { device_id: deviceId, pin, label: deviceLabel }),
    onSuccess: () => {
      onApproved()
    },
    onError: (err: any) => {
      setPin('')
      setError(err.response?.data?.detail || 'Wrong PIN')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (pin.length < 4) return
    setError('')
    verifyMutation.mutate()
  }

  if (blocked) {
    return (
      <div className="min-h-screen bg-sol-dark flex items-center justify-center">
        <div className="bg-sol-card border border-red-800/50 rounded-2xl p-10 w-full max-w-sm text-center space-y-4">
          <ShieldOff size={40} className="text-red-400 mx-auto" />
          <h2 className="text-xl font-bold text-white">Device Blocked</h2>
          <p className="text-gray-400 text-sm">
            This device has been blocked after too many incorrect PIN attempts.
            Ask the account owner to unblock it from the Settings page.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-sol-dark flex items-center justify-center">
      <div className="bg-sol-card border border-sol-border rounded-2xl p-10 w-full max-w-sm text-center space-y-6">
        <div>
          <Lock size={36} className="text-sol-accent mx-auto mb-3" />
          <h2 className="text-xl font-bold text-white">Enter PIN</h2>
          <p className="text-gray-400 text-sm mt-1">This device needs to be verified</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={8}
            value={pin}
            onChange={e => setPin(e.target.value.replace(/\D/g, ''))}
            placeholder="Enter PIN"
            className="w-full bg-sol-dark border border-sol-border rounded-xl px-4 py-3 text-white text-center text-xl tracking-widest focus:outline-none focus:border-sol-accent"
            autoFocus
          />

          {error && (
            <p className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-4 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={pin.length < 4 || verifyMutation.isPending}
            className="w-full flex items-center justify-center gap-2 bg-sol-accent hover:bg-sol-accent/80 disabled:opacity-50 text-white font-medium py-3 px-6 rounded-xl transition-colors"
          >
            {verifyMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Lock size={18} />}
            Verify
          </button>
        </form>

        <p className="text-gray-600 text-xs">
          2 wrong attempts will block this device.
        </p>
      </div>
    </div>
  )
}
