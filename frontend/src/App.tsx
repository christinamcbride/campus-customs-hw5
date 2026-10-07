/**
 * The Chapel Street desk.
 *
 * Three columns, matching how the work actually moves: the board on the left
 * (what came in), the work surface in the middle (what the team is doing
 * about it), and the money on the right (what it costs and who has to sign).
 *
 * The right rail is deliberately separate from the middle. Agent activity and
 * human authority are different kinds of thing, and putting an Approve button
 * inside the stream of agent chatter would blur the one boundary this whole
 * project exists to hold.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, money } from './api'
import { look } from './agents'
import ActivityFeed from './components/ActivityFeed'
import Decision from './components/Decision'
import Icon from './components/Icon'
import MoneyRail from './components/MoneyRail'
import { usePoll } from './hooks/usePoll'
import type {
  AgentEvent,
  Approval,
  Cash,
  Draft,
  Health,
  RunRecord,
  Ticket,
} from './types'
import './styles/theme.css'
import './styles/app.css'

const TICKET_TYPES: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Discount request',
}

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [cash, setCash] = useState<Cash | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])

  const [runId, setRunId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [record, setRecord] = useState<RunRecord | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const [operator, setOperator] = useState('Christina McBride')
  const [busyApproval, setBusyApproval] = useState<number | null>(null)
  const [outcomes, setOutcomes] = useState<Record<number, { text: string; bad: boolean }>>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [settling, setSettling] = useState(false)
  const lastBalance = useRef<number | null>(null)

  const ticket = tickets.find((t) => t.id === selected) ?? null

  /** Everything the desk shows except the live feed. */
  const refreshDesk = useCallback(async () => {
    try {
      const [t, c, a, d] = await Promise.all([
        api.tickets(),
        api.cash(),
        api.approvals(),
        api.drafts(),
      ])
      setTickets(t)
      setApprovals(a)
      setDrafts(d)
      setCash(c)
      setProblem(null)
      // Flash the till only on a real change, not on every poll.
      if (lastBalance.current !== null && lastBalance.current !== c.balance) {
        setSettling(true)
        window.setTimeout(() => setSettling(false), 1150)
      }
      lastBalance.current = c.balance
      setSelected((current) => current ?? t[0]?.id ?? null)
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    void api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  // Poll briskly while the team is out, slowly when the desk is quiet.
  usePoll(refreshDesk, running ? 2500 : 15000, [running])

  usePoll(
    async () => {
      if (!runId) return
      try {
        const fresh = await api.events(0, runId)
        setEvents(fresh)
        const state = await api.run(runId)
        if (state.status !== 'running') {
          setRunning(false)
          setRecord(state.record ?? null)
          if (state.status === 'failed') setRunError(state.error ?? 'The run failed.')
          void refreshDesk()
        }
      } catch {
        /* a dropped poll is not worth a banner; the next one will land */
      }
    },
    runId && running ? 1500 : null,
    [runId, running],
  )

  /**
   * Selecting a ticket loads the last run worked on it, if there was one, so
   * the desk still shows its history after a reload rather than looking as
   * though nothing ever happened.
   */
  const selectTicket = useCallback(async (id: number) => {
    setSelected(id)
    setRecord(null)
    setRunError(null)
    setEvents([])
    setRunId(null)
    try {
      const { runs } = await api.runs()
      const previous = runs.filter((r) => r.ticket_id === id).pop()
      if (!previous || previous.status === 'running') return
      setRunId(previous.run_id)
      setRecord(previous.record ?? null)
      if (previous.status === 'failed') setRunError(previous.error ?? 'The run failed.')
      setEvents(await api.events(0, previous.run_id))
    } catch {
      /* no history is not an error worth a banner */
    }
  }, [])

  const startRun = async () => {
    if (!ticket) return
    setRunning(true)
    setRecord(null)
    setRunError(null)
    setEvents([])
    setNotice(null)
    try {
      const started = await api.startRun(ticket.id, operator || 'shop operator')
      setRunId(started.run_id)
    } catch (err) {
      setRunning(false)
      setRunError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const decide = async (approval: Approval, decision: 'approve' | 'reject') => {
    setBusyApproval(approval.id)
    setOutcomes((o) => ({ ...o, [approval.id]: undefined as never }))
    try {
      const result = await api.decide(approval.id, {
        decision,
        decided_by: operator.trim(),
        note: 'Decided at the desk.',
      })
      setOutcomes((o) => ({ ...o, [approval.id]: { text: result.message, bad: false } }))
      setNotice(result.message)
      await refreshDesk()
      if (runId) setEvents(await api.events(0, runId))
    } catch (err) {
      // A refusal here is the shop's rules talking, so show its own wording.
      setOutcomes((o) => ({
        ...o,
        [approval.id]: {
          text: err instanceof ApiError ? err.message : String(err),
          bad: true,
        },
      }))
      await refreshDesk()
    } finally {
      setBusyApproval(null)
    }
  }

  const markResolved = async () => {
    if (!ticket) return
    setNotice(null)
    try {
      await api.resolveTicket(ticket.id, operator.trim() || 'shop operator')
      setNotice(`Ticket #${ticket.id} closed.`)
      await refreshDesk()
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : String(err))
    }
  }

  const reset = async () => {
    setNotice(null)
    try {
      const result = await api.reset()
      setEvents([])
      setRunId(null)
      setRecord(null)
      setRunError(null)
      setOutcomes({})
      lastBalance.current = null
      setNotice(result.message)
      await refreshDesk()
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : String(err))
    }
  }

  const ticketHasPending = useMemo(
    () =>
      approvals.some((a) => a.status === 'pending' && a.ticket_id === ticket?.id),
    [approvals, ticket],
  )

  const resolvedCount = useMemo(
    () => tickets.filter((t) => t.is_resolved).length,
    [tickets],
  )

  return (
    <div className="desk">
      <header className="counter">
        <div>
          <h1>Campus Customs — the desk</h1>
          <p className="shopdate">
            Chapel Street, New Haven · shop date <b>{cash?.as_of ?? '—'}</b>
            {health && (
              <>
                {' '}· team of <b>{health.agents.length}</b> on <b>{health.model}</b>
              </>
            )}
          </p>
        </div>

        <div className="counter-right">
          <div className="till">
            <span className="label">Checking</span>
            <span className={`amount${settling ? ' settling' : ''}`}>
              {cash ? money(cash.balance) : '—'}
            </span>
          </div>
          <button className="btn" onClick={reset} title="Restore the opening state">
            <Icon name="reset" size={15} />
            Reset the shop
          </button>
        </div>
      </header>

      {/* ---------------- the board ---------------- */}
      <nav className="rail board" aria-label="Ticket board">
        <h2 className="rail-title">
          On the board
          <span className="count">
            {resolvedCount}/{tickets.length} done
          </span>
        </h2>

        {tickets.length === 0 && !problem && (
          <div className="skeleton" style={{ height: '6rem' }} />
        )}

        <ul className="tickets">
          {tickets.map((t) => (
            <li key={t.id}>
              <button
                className={`ticket${t.is_resolved ? ' resolved' : ''}`}
                aria-current={t.id === selected}
                onClick={() => void selectTicket(t.id)}
              >
                <div className="ticket-head">
                  <span className="no figures">#{t.id}</span>
                  <span className={`chip ${t.status}`}>
                    {t.is_resolved && <Icon name="stamp" size={11} />}
                    {t.status.replace(/_/g, ' ')}
                  </span>
                </div>
                <span className="subject">{t.subject}</span>
                <span className="who">
                  {TICKET_TYPES[t.type] ?? t.type} · {t.requester}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* ---------------- the work surface ---------------- */}
      <main className="work">
        {problem && (
          <div className="banner bad" role="alert">
            <Icon name="alert" size={17} />
            <span>{problem}</span>
          </div>
        )}
        {notice && !problem && (
          <div className="banner good" role="status">
            <Icon name="check" size={17} />
            <span>{notice}</span>
          </div>
        )}

        {!ticket ? (
          <div className="feed-empty">Pick a ticket from the board to begin.</div>
        ) : (
          <>
            <section className="sheet ticket-detail">
              <div className="detail-head">
                <div>
                  <h2>{ticket.subject}</h2>
                  <div className="facts">
                    <span>
                      ticket <b>#{ticket.id}</b>
                    </span>
                    <span>
                      from <b>{ticket.requester}</b>
                    </span>
                    {ticket.sku && (
                      <span>
                        <b>
                          {ticket.sku}
                          {ticket.size ? ` · ${ticket.size}` : ''}
                          {ticket.qty ? ` × ${ticket.qty}` : ''}
                        </b>
                      </span>
                    )}
                    {ticket.lease_id && (
                      <span>
                        lease <b>{ticket.lease_id}</b>
                      </span>
                    )}
                    {ticket.invoice_id && (
                      <span>
                        invoice <b>{ticket.invoice_id}</b>
                      </span>
                    )}
                  </div>
                </div>
                <span className={`chip ${ticket.status}`}>
                  {ticket.is_resolved && <Icon name="stamp" size={11} />}
                  {ticket.status.replace(/_/g, ' ')}
                </span>
              </div>

              {ticket.notes && (
                <p className="ask">
                  <q>{ticket.notes.split('\n')[0]}</q>
                </p>
              )}

              <div className="run-bar">
                <button
                  className="btn primary"
                  onClick={startRun}
                  disabled={running || !health?.agent_team_ready}
                >
                  <Icon name="play" size={14} />
                  {running ? 'Team is working…' : 'Call the team in'}
                </button>

                {running && (
                  <span className="working">
                    <span className="dot" />
                    working the ticket
                  </span>
                )}

                {!health?.agent_team_ready && (
                  <p className="run-note">
                    No <code>PORTKEY_API_KEY</code> is set, so the team cannot run.
                  </p>
                )}
                {health?.agent_team_ready && !running && (
                  <p className="run-note">
                    The team can read the shop and prepare a payment. It cannot
                    spend anything — that needs you.
                  </p>
                )}

                {!ticket.is_resolved && ticket.status !== 'open' && !running && (
                  <button
                    className="btn"
                    onClick={markResolved}
                    disabled={ticketHasPending}
                    title={
                      ticketHasPending
                        ? 'Something on this ticket is still waiting on your decision.'
                        : 'Close this ticket off'
                    }
                  >
                    <Icon name="stamp" size={14} />
                    Mark resolved
                  </button>
                )}
              </div>
            </section>

            {runError && (
              <div className="banner bad" role="alert" style={{ marginTop: '1.2rem' }}>
                <Icon name="alert" size={17} />
                <span>{runError}</span>
              </div>
            )}

            <div className="section-head">
              <h3>Agent activity</h3>
              {record && (
                <span className="meta">
                  {(record.duration_ms / 1000).toFixed(1)}s ·{' '}
                  {record.tool_calls} tool calls ·{' '}
                  {record.total_tokens.toLocaleString()} tokens
                </span>
              )}
            </div>

            <ActivityFeed events={events} running={running} hasRun={!!runId} />

            {record && (
              <>
                <div className="section-head">
                  <h3>What the team decided</h3>
                  {record.decision && (
                    <span className="meta">
                      {record.decision.consulted.map((c) => look(c).title).join(' · ')}
                    </span>
                  )}
                </div>
                <Decision record={record} events={events} />
              </>
            )}
          </>
        )}
      </main>

      {/* ---------------- the money ---------------- */}
      <MoneyRail
        cash={cash}
        approvals={approvals}
        drafts={drafts}
        operator={operator}
        onOperator={setOperator}
        onDecide={decide}
        busyApproval={busyApproval}
        outcomes={outcomes}
      />
    </div>
  )
}
