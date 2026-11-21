export const API_URL = import.meta.env.VITE_API_URL ?? "https://ada-hackathon-production.up.railway.app";

export async function fetchState() {
  const res = await fetch(`${API_URL}/state`, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(12000),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.detail ?? res.statusText;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

export const runScenario     = (name)             => post(`/admin/scenario/${name}`);
export const resetSimulation = ()                 => post('/admin/reset');
export const triggerAnalysis = ()                 => post('/agent/analyze');
export const approveOption   = (runId, idx)       => post(`/agent/runs/${runId}/approve`, { option_index: idx });
export const rejectRun       = (runId)            => post(`/agent/runs/${runId}/reject`,  { reason: null });
