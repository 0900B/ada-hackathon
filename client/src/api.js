const API_URL = "https://ada-hackathon-production.up.railway.app";

export async function fetchState() {
  const res = await fetch(`${API_URL}/state`, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
