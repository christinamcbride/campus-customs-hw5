/**
 * What the team concluded, and a short note on what each agent contributed.
 *
 * The per-agent summary is built from the run's own events rather than from
 * the boss's prose — the boss names who it consulted, but the trail knows
 * what each of them actually did, and those are not always the same thing.
 */

import { look } from '../agents'
import type { AgentEvent, RunRecord } from '../types'
import Icon from './Icon'

interface AgentWork {
  agent: string
  tools: string[]
  said: string | null
}

function perAgent(events: AgentEvent[]): AgentWork[] {
  const byAgent = new Map<string, AgentWork>()
  for (const e of events) {
    if (!e.agent) continue
    const entry = byAgent.get(e.agent) ?? { agent: e.agent, tools: [], said: null }
    if (e.event === 'tool_call' && e.tool && !entry.tools.includes(e.tool)) {
      entry.tools.push(e.tool)
    }
    if (e.event === 'delegation_returned' && e.said) entry.said = e.said
    byAgent.set(e.agent, entry)
  }
  // Boss first, then whoever it brought in, in the order they were called.
  return [...byAgent.values()].sort((a, b) =>
    a.agent === 'boss' ? -1 : b.agent === 'boss' ? 1 : 0,
  )
}

export default function Decision({
  record,
  events,
}: {
  record: RunRecord
  events: AgentEvent[]
}) {
  const d = record.decision
  const work = perAgent(events)

  if (!d) {
    return (
      <div className="sheet verdict-sheet">
        <div className="banner bad" style={{ marginBottom: 0 }}>
          <Icon name="alert" size={17} />
          <div>
            <strong>The run stopped: {record.stop_reason.replace(/_/g, ' ')}.</strong>
            {record.error && <div style={{ marginTop: '.3rem' }}>{record.error}</div>}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="sheet verdict-sheet">
      <p className="decision">{d.decision}</p>
      <p className="rationale">{d.rationale}</p>

      <div className="who-did-what">
        {work.map((w) => {
          const l = look(w.agent)
          return (
            <div className="did" key={w.agent} style={l.vars}>
              <span className="mark small" aria-hidden="true">
                <Icon name={l.icon} size={11} />
              </span>
              <div>
                <span className="name">{l.title}</span>
                <p className="what">
                  {w.said ??
                    (w.agent === 'boss'
                      ? 'Read the ticket, routed the work, and made the call.'
                      : 'Worked the ticket from its own tools.')}
                  {w.tools.length > 0 && (
                    <>
                      {' '}
                      <span className="count">
                        {w.tools.length} tool{w.tools.length === 1 ? '' : 's'}:{' '}
                        {w.tools.join(', ')}
                      </span>
                    </>
                  )}
                </p>
              </div>
            </div>
          )
        })}
      </div>

      {d.actions_taken.length > 0 && (
        <ul className="ledger-list">
          <h4>What changed in the shop</h4>
          {d.actions_taken.map((a, i) => (
            <li key={i}>
              <Icon name="check" size={13} />
              <span>{a}</span>
            </li>
          ))}
        </ul>
      )}

      {d.findings.length > 0 && (
        <ul className="ledger-list">
          <h4>What they found</h4>
          {d.findings.map((f, i) => (
            <li key={i}>
              <Icon name="tool" size={13} />
              <span>
                {f.fact} <span className="source">— {f.source_tool}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {d.unknowns.length > 0 && (
        <ul className="ledger-list gaps">
          <h4>What they could not establish</h4>
          {d.unknowns.map((u, i) => (
            <li key={i}>
              <Icon name="alert" size={13} />
              <span>{u}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
