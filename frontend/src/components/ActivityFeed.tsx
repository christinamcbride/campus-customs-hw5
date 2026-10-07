/**
 * The agent feed.
 *
 * Four kinds of line, each shaped differently so the desk can be read at a
 * glance rather than parsed:
 *
 *   tool      an instrument reading — set in the ledger hand, with the value
 *             that came back
 *   handoff   one agent passing work to another — two marks and an arrow,
 *             not a sentence
 *   spoke     what an agent actually reported, quoted in that agent's ink
 *   milestone the run starting, stopping, or a human deciding
 *
 * Colour alone never carries the distinction: every line also has the
 * agent's drawn mark and its own layout.
 */

import { useEffect, useRef } from 'react'
import { clockTime } from '../api'
import { look } from '../agents'
import type { AgentEvent } from '../types'
import Icon from './Icon'

/** Pull the one figure worth showing from whatever a tool returned. */
function verdictOf(event: AgentEvent): { text: string; bad: boolean } | null {
  if (event.error) {
    const short = event.error.replace(/^\w+:\s*/, '')
    return { text: short.length > 72 ? short.slice(0, 72) + '…' : short, bad: true }
  }
  const r = event.result
  if (r === null || r === undefined) return null

  if (typeof r === 'object' && !Array.isArray(r)) {
    const o = r as Record<string, unknown>
    const picks: [string, (v: unknown) => string][] = [
      ['quantity_on_hand', (v) => `${v} on hand`],
      ['balance', (v) => `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2 })}`],
      ['days_until_due', (v) => `${v} days to due`],
      ['list_margin_percent', (v) => `${v}% at list`],
      ['status', (v) => String(v)],
      ['amount', (v) => `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2 })}`],
      ['count', (v) => `${v} row${v === 1 ? '' : 's'}`],
    ]
    for (const [key, fmt] of picks) {
      if (o[key] !== undefined && o[key] !== null) return { text: fmt(o[key]), bad: false }
    }
    if (typeof o.summary === 'string') return null
  }
  return null
}

function argSummary(args: unknown): string {
  if (!args || typeof args !== 'object') return ''
  const entries = Object.entries(args as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .slice(0, 3)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
  return entries.length ? `(${entries.join(', ')})` : '()'
}

function Line({ event }: { event: AgentEvent }) {
  const actor = look(event.agent)
  const at = clockTime(event.time)

  // --- a handoff between two agents -------------------------------------
  if (event.event === 'delegation' || event.event === 'delegation_refused') {
    const to = event.action?.split('->')[1] ?? ''
    const target = look(to)
    const refused = event.event === 'delegation_refused'
    return (
      <li
        className={`entry handoff${refused ? ' refused' : ''}`}
        style={
          {
            ...actor.vars,
            '--from-hue': `var(--${event.agent ?? 'ink-2'})`,
            '--to-hue': `var(--${to || 'ink-2'})`,
          } as React.CSSProperties
        }
      >
        <span className="at figures">{at}</span>
        <span className="mark" aria-hidden="true">
          <Icon name={actor.icon} size={13} />
        </span>
        <div className="body">
          <span className="handoff-pair">
            <span className="from">{actor.title}</span>
            <Icon name={refused ? 'cross' : 'arrow'} size={14} />
            <span className="to">{target.title}</span>
          </span>
          {refused ? (
            <span>
              handoff refused — {event.stop_reason?.replace(/_/g, ' ')}
            </span>
          ) : (
            event.said && <span className="task">“{event.said}”</span>
          )}
        </div>
      </li>
    )
  }

  // --- a tool call -------------------------------------------------------
  if (event.event === 'tool_call') {
    const verdict = verdictOf(event)
    return (
      <li className="entry tool" style={actor.vars}>
        <span className="at figures">{at}</span>
        <span className="mark" aria-hidden="true">
          <Icon name={actor.icon} size={13} />
        </span>
        <div className="body">
          <div className="agent-name">{actor.title}</div>
          <div className="line">
            <span className="tool-name">{event.tool}</span>
            <span className="args">{argSummary(event.arguments)}</span>
            {verdict && (
              <span className={`verdict${verdict.bad ? ' bad' : ''}`}>{verdict.text}</span>
            )}
          </div>
        </div>
      </li>
    )
  }

  // --- an agent reporting back ------------------------------------------
  if (event.event === 'delegation_returned' && event.said) {
    return (
      <li className="entry spoke" style={actor.vars}>
        <span className="at figures">{at}</span>
        <span className="mark" aria-hidden="true">
          <Icon name={actor.icon} size={13} />
        </span>
        <div className="body">
          <div className="agent-name">{actor.title} reported</div>
          <p className="said">{event.said}</p>
        </div>
      </li>
    )
  }

  // --- run boundaries and desk actions ----------------------------------
  const milestones: Record<string, string> = {
    run_started: 'Team called in',
    run_finished: 'Team stood down',
    human_decision: 'Desk decision',
    shop_reset: 'Shop reset',
  }
  if (milestones[event.event]) {
    return (
      <li className="entry milestone" style={actor.vars}>
        <span className="at figures">{at}</span>
        <span className="mark" aria-hidden="true">
          <Icon name={event.event === 'run_finished' ? 'check' : 'clock'} size={13} />
        </span>
        <div className="body">
          <span>{milestones[event.event]}</span>
          {event.stop_reason && (
            <span className="stamp">{event.stop_reason.replace(/_/g, ' ')}</span>
          )}
          {event.usage && (
            <span className="stamp">
              {event.usage.total_tokens.toLocaleString()} tokens ·{' '}
              {event.usage.tool_calls} tool calls
            </span>
          )}
        </div>
      </li>
    )
  }

  return null
}

interface Props {
  events: AgentEvent[]
  running: boolean
  hasRun: boolean
}

export default function ActivityFeed({ events, running, hasRun }: Props) {
  const end = useRef<HTMLDivElement>(null)

  // Follow the conversation while it is live, but leave the reader alone
  // once it has finished — nothing is more annoying than a log that yanks
  // you back to the bottom while you are reading the middle of it.
  useEffect(() => {
    if (running) end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length, running])

  if (!events.length) {
    return (
      <div className="feed-empty">
        {hasRun
          ? 'No activity recorded for this run yet.'
          : 'Nothing yet. Call the team in and their work appears here, line by line.'}
      </div>
    )
  }

  return (
    <>
      <ul className="feed">
        {events.map((e) => (
          <Line key={e.seq} event={e} />
        ))}
      </ul>
      <div ref={end} />
    </>
  )
}
