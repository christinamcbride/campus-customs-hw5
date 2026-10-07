/** Shapes returned by the FastAPI backend. Kept in step with backend/main.py. */

export type TicketStatus =
  | 'open'
  | 'in_progress'
  | 'waiting_approval'
  | 'blocked'
  | 'resolved'

export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  status: TicketStatus
  is_open: boolean
  is_resolved: boolean
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  notes: string | null
  created_at: string
}

export type RoleName =
  | 'boss'
  | 'inventory'
  | 'accounting'
  | 'facilities'
  | 'customer_service'

export interface AgentEvent {
  seq: number
  time: string
  event: string
  run_id: string
  agent: RoleName | null
  ticket_id: number | null
  action: string | null
  tool: string | null
  arguments: unknown
  result: unknown
  said: string | null
  depth: number | null
  stop_reason: string | null
  error: string | null
  duration_ms: number | null
  usage: Usage | null
}

export interface Usage {
  requests: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface Finding {
  fact: string
  source_tool: string
}

export interface TicketDecision {
  ticket_id: number
  decision: string
  rationale: string
  consulted: string[]
  findings: Finding[]
  actions_taken: string[]
  approval_ids_waiting: number[]
  customer_draft_ids: number[]
  ticket_status: TicketStatus
  unknowns: string[]
}

export interface RunRecord {
  run_id: string
  ticket_id: number
  ok: boolean
  stop_reason: string
  decision: TicketDecision | null
  error: string | null
  duration_ms: number
  requests: number
  tool_calls: number
  total_tokens: number
  delegations: string[]
}

export interface RunState {
  status: 'running' | 'finished' | 'failed'
  ticket_id: number
  record?: RunRecord
  error?: string
  stop_reason?: string
}

export interface Approval {
  id: number
  kind: 'payment' | 'purchase_order'
  ticket_id: number | null
  requested_by: string
  summary: string
  amount: number
  account: string | null
  payload: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected' | 'executed'
  created_at: string
  decided_at: string | null
  decided_by: string | null
  decision_note: string | null
  executed_at: string | null
}

export interface Cash {
  account: string
  balance: number
  as_of: string
  committed_to_pending_approvals: number
  uncommitted: number
}

export interface DecisionResult {
  approval_id: number
  kind: string
  decision: string
  decided_by: string
  executed: boolean
  receipt: Record<string, unknown> | null
  balance_after: number | null
  message: string
}

export interface Draft {
  id: number
  ticket_id: number
  drafted_by: string
  recipient: string
  subject: string
  body: string
  created_at: string
  status: string
}

export interface Health {
  ok: boolean
  model: string
  agent_team_ready: boolean
  agents: string[]
  mcp_tools: string[]
  limits: {
    requests: number
    tool_calls: number
    total_tokens: number
    delegation_depth: number
  }
}

export interface Decision {
  decision: 'approve' | 'reject'
  decided_by: string
  note?: string
}
