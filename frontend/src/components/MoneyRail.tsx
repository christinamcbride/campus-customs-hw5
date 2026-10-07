/**
 * The money rail: the till, the approval queue, and the drafts on the board.
 *
 * The approval queue is the one place in this dashboard where a click costs
 * the shop money, so it is given its own colour (the hold amber), its own
 * card weight, and a name field — the person approving is recorded in
 * `payments.approved_by`, and the form should make that obvious rather than
 * hide it.
 */

import { money } from '../api'
import { look } from '../agents'
import type { Approval, Cash, Draft } from '../types'
import Icon from './Icon'

interface Props {
  cash: Cash | null
  approvals: Approval[]
  drafts: Draft[]
  operator: string
  onOperator: (name: string) => void
  onDecide: (approval: Approval, decision: 'approve' | 'reject') => void
  busyApproval: number | null
  outcomes: Record<number, { text: string; bad: boolean }>
}

export default function MoneyRail({
  cash,
  approvals,
  drafts,
  operator,
  onOperator,
  onDecide,
  busyApproval,
  outcomes,
}: Props) {
  const pending = approvals.filter((a) => a.status === 'pending')
  const settled = approvals.filter((a) => a.status !== 'pending')

  return (
    <aside className="rail money" aria-label="Money and approvals">
      <section>
        <h2 className="rail-title">
          Waiting on you
          <span className="count">{pending.length}</span>
        </h2>

        {pending.length === 0 ? (
          <p className="empty">
            Nothing to approve. The agents can queue a payment, but only you can
            make one.
          </p>
        ) : (
          <>
            <div className="who-field" style={{ marginBottom: '.8rem' }}>
              <label htmlFor="operator">Approving as</label>
              <input
                id="operator"
                value={operator}
                onChange={(e) => onOperator(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
              />
            </div>

            {pending.map((a) => {
              const asker = look(a.requested_by)
              const outcome = outcomes[a.id]
              return (
                <article className="approval" key={a.id} style={asker.vars}>
                  <div className="approval-top">
                    <span className="kind">
                      {a.kind === 'payment' ? 'Payment' : 'Purchase order'}
                    </span>
                    <span className="amount">{money(a.amount)}</span>
                  </div>
                  <p className="summary">{a.summary}</p>
                  <div className="asked-by">
                    <span className="mark small" aria-hidden="true">
                      <Icon name={asker.icon} size={11} />
                    </span>
                    prepared by <b>{asker.title}</b>
                    {a.ticket_id && <>· ticket {a.ticket_id}</>}
                  </div>

                  {outcome && (
                    <p className={`outcome${outcome.bad ? ' bad' : ''}`}>
                      <Icon name={outcome.bad ? 'alert' : 'check'} size={13} />
                      <span>{outcome.text}</span>
                    </p>
                  )}

                  <div className="approval-actions">
                    <button
                      className="btn go small"
                      disabled={busyApproval === a.id || !operator.trim()}
                      onClick={() => onDecide(a, 'approve')}
                    >
                      <Icon name="check" size={14} />
                      {a.kind === 'payment' ? 'Approve & pay' : 'Approve & order'}
                    </button>
                    <button
                      className="btn quiet small"
                      disabled={busyApproval === a.id || !operator.trim()}
                      onClick={() => onDecide(a, 'reject')}
                    >
                      <Icon name="cross" size={14} />
                      Reject
                    </button>
                  </div>
                </article>
              )
            })}
          </>
        )}
      </section>

      <section>
        <h2 className="rail-title">The till</h2>
        <div className="sheet till-sheet">
          {cash ? (
            <>
              <dl className="till-rows">
                <div className="till-row">
                  <dt>In {cash.account}</dt>
                  <dd>{money(cash.balance)}</dd>
                </div>
                <div className="till-row committed">
                  <dt>Queued for approval</dt>
                  <dd>
                    {cash.committed_to_pending_approvals > 0 ? '−' : ''}
                    {money(cash.committed_to_pending_approvals)}
                  </dd>
                </div>
                <div className="till-row">
                  <dt>Free to spend</dt>
                  <dd>{money(cash.uncommitted)}</dd>
                </div>
              </dl>
              <p className="till-note">
                No revenue is modelled, so this only ever falls. Two payments that
                each fit may not fit together — spend against{' '}
                <em>free to spend</em>, not the balance.
              </p>
            </>
          ) : (
            <div className="skeleton" style={{ height: '5.5rem' }} />
          )}
        </div>
      </section>

      {settled.length > 0 && (
        <section>
          <h2 className="rail-title">
            Already decided
            <span className="count">{settled.length}</span>
          </h2>
          {settled.map((a) => (
            <article className="approval settled" key={a.id}>
              <div className="approval-top">
                <span className="kind">
                  {a.status === 'executed'
                    ? a.kind === 'payment'
                      ? 'Paid'
                      : 'Ordered'
                    : a.status}
                </span>
                <span className="amount">{money(a.amount)}</span>
              </div>
              <p className="summary">{a.summary}</p>
              {a.decided_by && (
                <div className="asked-by">
                  <Icon name="stamp" size={12} />
                  {a.status === 'rejected' ? 'rejected' : 'approved'} by {a.decided_by}
                </div>
              )}
            </article>
          ))}
        </section>
      )}

      {drafts.length > 0 && (
        <section>
          <h2 className="rail-title">
            Drafts on the board
            <span className="count">{drafts.length}</span>
          </h2>
          {drafts.map((d) => (
            <article className="draft" key={d.id}>
              <div className="to">To {d.recipient} · ticket {d.ticket_id}</div>
              <h3 className="subject">{d.subject}</h3>
              <div className={`body${d.body.length > 320 ? ' clipped' : ''}`}>
                {d.body}
              </div>
              <span className="unsent">
                <Icon name="quill" size={12} />
                Not sent
              </span>
            </article>
          ))}
        </section>
      )}
    </aside>
  )
}
