// KubeMind — REST API client (Production Edition)
const BASE = (process.env.NEXT_PUBLIC_API_URL || '').trim() || 'http://localhost:8000';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('kubemind_token');
}

function authHeaders(): HeadersInit {
  const token = getToken();
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) (headers as Record<string,string>)['Authorization'] = `Bearer ${token}`;
  return headers;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: 'no-store', headers: authHeaders() });
  if (r.status === 401) { if (typeof window !== 'undefined') window.dispatchEvent(new Event('kubemind:unauthorized')); }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
  if (r.status === 401) { if (typeof window !== 'undefined') window.dispatchEvent(new Event('kubemind:unauthorized')); }
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: 'DELETE', headers: authHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export const api = {
  // Auth
  register: (data: { email: string; password: string; name: string; organization?: string }) =>
    post<{ token: string; user: any }>('/api/v1/auth/register', data),
  login: (email: string, password: string) =>
    post<{ token: string; user: any }>('/api/v1/auth/login', { email, password }),
  me: () => get<any>('/api/v1/auth/me'),

  // Clusters
  listClusters: () => get<any[]>('/api/v1/clusters'),
  registerCluster: (name: string, provider: string) =>
    post<any>('/api/v1/clusters', { name, provider }),
  getCluster: (id: string) => get<any>(`/api/v1/clusters/${id}`),
  deleteCluster: (id: string) => del<any>(`/api/v1/clusters/${id}`),
  getInstallCommand: (id: string) => get<{ install_command: string }>(`/api/v1/clusters/${id}/install-command`),

  // Existing
  health: () => get('/api/v1/health'),
  summary: () => get('/api/v1/cluster/summary'),
  metrics: () => get('/api/v1/metrics'),
  serviceMetrics: (svc: string) => get(`/api/v1/metrics/${svc}`),
  topology: () => get('/api/v1/topology'),
  anomalies: () => get('/api/v1/anomalies'),
  anomalyHistory: (limit = 50) => get(`/api/v1/anomalies/history?limit=${limit}`),
  rca: () => get('/api/v1/rca'),
  faults: () => get('/api/v1/faults'),
  insights: () => get<any[]>('/api/v1/insights'),
  injectFault: (service: string, fault_type: string, duration = 120) =>
    post(`/api/v1/fault/inject?service=${encodeURIComponent(service)}&fault_type=${fault_type}&duration=${duration}`, {}),
  clearFault: (service: string) =>
    post(`/api/v1/fault/clear?service=${encodeURIComponent(service)}`, {}),
  aiQuery: (query: string) =>
    post<{ query: string; response: string; source: string; context: string }>('/api/v1/ai/query', { query }),

  // Correlation Intelligence
  correlation: () => get<any>('/api/v1/correlation'),
  healthScore: () => get<any>('/api/v1/health-score'),
  exhaustion: () => get<any>('/api/v1/exhaustion'),
};
