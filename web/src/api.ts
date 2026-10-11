export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export async function api<T>(token: string, path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail), response.status)
  }
  return response.json() as Promise<T>
}
