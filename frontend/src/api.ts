/**
 * The backend, at http://localhost:8000.
 *
 * Calls go cross-origin rather than through a Vite proxy, which is why the
 * backend lists the dev-server origins in its CORS middleware. Override the
 * host with VITE_API_BASE if the backend is somewhere else.
 */

import type {
  Approval,
  Cash,
  Decision,
  DecisionResult,
  Draft,
  AgentEvent,
  Health,
  RunState,
  Ticket,
} from './types'

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

/** Carries the backend's own wording so the desk can show the shop's reason. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(API_BASE + path, {
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    })
  } catch {
    throw new ApiError(
      `Cannot reach the backend at ${API_BASE}. Start it with: cd backend && uvicorn main:app --reload --port 8000`,
      0,
    )
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail) && body.detail.length) {
        // FastAPI validation errors arrive as a list of field problems.
        const first = body.detail[0] as { msg?: string; loc?: string[] }
        detail = `${first.loc?.slice(-1)[0] ?? 'input'}: ${first.msg ?? 'invalid'}`
      }
    } catch {
      /* keep the status line */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  tickets: () => request<Ticket[]>('/api/tickets'),
  cash: () => request<Cash>('/api/cash'),
  approvals: () => request<Approval[]>('/api/approvals'),
  drafts: () => request<Draft[]>('/api/drafts'),

  events: (since = 0, runId?: string) =>
    request<AgentEvent[]>(
      `/api/events?since=${since}&limit=400` + (runId ? `&run_id=${runId}` : ''),
    ),

  startRun: (ticketId: number, operator: string) =>
    request<{ run_id: string; ticket_id: number }>(
      `/api/tickets/${ticketId}/run?operator=${encodeURIComponent(operator)}`,
      { method: 'POST' },
    ),

  run: (runId: string) => request<RunState>(`/api/runs/${runId}`),

  runs: () => request<{ runs: (RunState & { run_id: string })[] }>('/api/runs'),

  resolveTicket: (ticketId: number, resolvedBy: string) =>
    request<Ticket>(`/api/tickets/${ticketId}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ resolved_by: resolvedBy }),
    }),

  decide: (approvalId: number, body: Decision) =>
    request<DecisionResult>(`/api/approvals/${approvalId}/decide`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  reset: () =>
    request<{ reset: boolean; tickets_open: number; balance: number; message: string }>(
      '/api/reset',
      { method: 'POST' },
    ),
}

export const money = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export const clockTime = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString('en-US', { hour12: false })
}
