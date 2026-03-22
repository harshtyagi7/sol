import { useEffect, useRef, useState, useCallback } from 'react'

export interface WSEvent {
  type: string
  data?: any
}

export function useWebSocket(path: string, onEvent: (event: WSEvent) => void) {
  const ws = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}${path}`
    const socket = new WebSocket(url)

    socket.onopen = () => setConnected(true)
    socket.onclose = () => {
      setConnected(false)
      // Reconnect after 3s
      setTimeout(connect, 3000)
    }
    socket.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        if (event.type !== 'ping') onEventRef.current(event)
      } catch {}
    }
    socket.onerror = () => socket.close()
    ws.current = socket
  }, [path])

  useEffect(() => {
    connect()
    return () => ws.current?.close()
  }, [connect])

  return { connected }
}
