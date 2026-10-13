// Thin client for the ClinScribe API (apps/api/clinical.py). The token stays in memory only.
let token = null;

export function setToken(value) {
  token = value;
}

export async function call(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    throw new Error(`${response.status}: ${detail}`);
  }
  return data;
}
