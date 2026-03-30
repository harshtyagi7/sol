import axios from 'axios'

export const api = axios.create({ baseURL: '/api' })

export const chatApi = {
  send: (message: string) => api.post('/chat', { message }),
  getHistory: (limit = 20) => api.get(`/chat/history?limit=${limit}`),
}

export const tradesApi = {
  getPending: () => api.get('/trades/proposals?status=pending'),
  getHistory: () => api.get('/trades/history'),
  review: (id: string, action: object) => api.post(`/trades/proposals/${id}/review`, action),
}

export const strategiesApi = {
  getPending: () => api.get('/strategies?status=pending'),
  getAll: () => api.get('/strategies'),
  get: (id: string) => api.get(`/strategies/${id}`),
  approve: (id: string, maxLossApproved: number, note?: string) =>
    api.post(`/strategies/${id}/approve`, { max_loss_approved: maxLossApproved, note }),
  reject: (id: string, note?: string) =>
    api.post(`/strategies/${id}/reject`, null, { params: note ? { note } : {} }),
  backtest: (id: string) => api.post(`/strategies/${id}/backtest`),
}

export const portfolioApi = {
  getSummary: () => api.get('/portfolio/summary'),
  getPositions: () => api.get('/portfolio/positions'),
  getTrades: () => api.get('/portfolio/trades'),
  closePosition: (id: string) => api.post(`/portfolio/positions/${id}/close`),
}

export const agentsApi = {
  list: () => api.get('/agents'),
  create: (data: object) => api.post('/agents', data),
  update: (id: string, data: object) => api.put(`/agents/${id}`, data),
  deactivate: (id: string) => api.delete(`/agents/${id}`),
  trigger: (id: string) => api.post(`/agents/${id}/trigger`),
}

export const riskApi = {
  getConfig: () => api.get('/risk/config'),
  updateConfig: (data: object) => api.put('/risk/config', data),
  getReport: () => api.get('/risk/report'),
}

export const dashboardApi = {
  get: () => api.get('/dashboard'),
}

export const newsApi = {
  getAll: () => api.get('/news'),
  getForSymbol: (symbol: string) => api.get(`/news/${symbol}`),
}

export const optionsApi = {
  getStatus: () => api.get('/options/status'),
  getChain: (underlying: string, strikes = 8) =>
    api.get(`/options/${underlying}?strikes=${strikes}`),
}

export const authApi = {
  getLoginUrl: () => api.get('/auth/login'),
  getStatus: () => api.get('/auth/status'),
}

export const settingsApi = {
  getMode: () => api.get('/settings/mode'),
  setMode: (paperTrading: boolean) => api.post(`/settings/mode?paper_trading=${paperTrading}`),
}
