# The Chapel Street Desk — dashboard design

The dashboard for Campus Customs Multi-Agent Operations: `frontend/`, React + Vite +
TypeScript, talking to the FastAPI backend at `http://localhost:8000`.

---

## 1. The scene this is designed for

Before any layout decision: who is using this, where, and under what light?

A person behind the counter of a print shop on Chapel Street, mid-afternoon, daylight
through one window. They are not monitoring a fleet — they have **three tickets**, one
cash account, and a team of five that keeps asking them to sign things. They will look
at this between customers, in thirty-second glances, and the question they arrive with
is almost always one of two: *what is the team doing?* or *what needs me?*

That scene decided several things at once. The ground is warm paper rather than a dark
console, because the room has daylight in it and a dark operations theme would be
costume rather than fit. The type is set at a reading size, not a telemetry size,
because there are three tickets and not three hundred. And the two questions above get
the two outside columns, so neither one requires scrolling to answer.

---

## 2. Layout

Three columns on a wide screen, matching how the work actually moves.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  THE COUNTER        Campus Customs — the desk        CHECKING  $3,400.00  │
│  shop date · team of 5 on gpt-6-luna                      [Reset the shop]│
├──────────────┬─────────────────────────────────────┬──────────────────────┤
│ ON THE BOARD │  Ticket detail — the ask, verbatim  │  WAITING ON YOU      │
│              │  [Call the team in]  [Mark resolved]│  approval cards      │
│  #101 ███    │                                     │  Approve & pay       │
│  #102 ███    │  AGENT ACTIVITY                     │  ───────────         │
│  #103 ███    │  live feed, one line per step       │  THE TILL            │
│              │                                     │  balance / queued /  │
│  what came   │  WHAT THE TEAM DECIDED              │  free to spend       │
│  in          │  decision · who did what · findings │  ───────────         │
│              │  · what changed · what they could   │  ALREADY DECIDED     │
│              │    not establish                    │  DRAFTS ON THE BOARD │
└──────────────┴─────────────────────────────────────┴──────────────────────┘
       what came in          what the team is doing        what it costs
                                                        and who has to sign
```

**The left rail is the board.** Three ticket cards, each showing the number, the
subject, who asked, and a status chip. It is a `<nav>`, and selecting a card is the
only navigation in the app.

**The middle is the work surface.** The selected ticket at the top with the requester's
own words quoted, then the run control, then the live activity feed, then the decision
once the run lands. It reads top to bottom in the order the work happens.

**The right rail is the money.** Approvals first, because that is the one thing the
page can ask of the person. Then the till, then what has already been decided, then
the drafts the team left on the board.

### Why the money is a separate column

This is the layout decision I would defend hardest.

Putting the **Approve** button inside the activity feed would have been easy — it is
where the request appears, after all. It is also exactly wrong. Agent activity and
human authority are different kinds of thing, and this entire project exists to hold
that line: agents prepare, people decide. A button that sits in the stream of agent
chatter reads like one more thing the agents did.

Keeping approvals in their own column, in their own colour, with the approver's name in
a field right above the button, makes the boundary visible in the layout itself. You
cannot approve a payment here without noticing that *you* are the one approving it.

### Responsive

At **1180px** the money rail drops below the board and the work surface — the two
reading columns stay side by side, because losing the ticket list while reading a run
would cost more than losing the till. At **820px** everything stacks in reading order:
counter, board, work, money. The counter stays sticky at every width, so the balance
and the reset control never scroll away.

---

## 3. How agent activity is differentiated

Five agents share one feed. The problem is making it legible at a glance without
turning into a wall of identical rows.

### Each agent has its own ink and its own mark

| Agent | Ink | Mark |
|---|---|---|
| Boss | `#1c3a66` navy | a desk bell — the boss is who you ring |
| Inventory | `#1b6350` green | a stock carton |
| Accounting | `#74470e` brass-brown | a balance scale |
| Facilities | `#563674` plum | the shopfront |
| Customer Service | `#93402e` terracotta | a written reply |

Colour is never the only carrier. Every line also shows the agent's **drawn mark** and
its **name in small caps**, so the feed is fully readable to someone who cannot
distinguish the hues. All five inks clear 5.8:1 against both rail grounds, so they work
as text and not only as decoration.

The marks are authored SVG on one 24×24 grid at a single 1.6 stroke — not emoji, not a
font. They are used at 11–14px inside the mark discs, which is why the glyphs are
simple enough to survive at that size.

### Four line shapes, not four colours of the same line

The important differentiation is **structural**. Each kind of step is laid out
differently, so you can tell what happened before you read a word:

- **Tool call** — set in the ledger mono: `check_rent_due(lease_id=1)` followed by a
  small chip with the figure that came back (`2 days to due`, `$3,400.00`, `0 on hand`).
  A failed call shows its refusal in the stop red. This is the line that proves a fact
  came from the database and not from the model.
- **Handoff** — two agent names in their own inks with a brass arrow between them, then
  the task in italics. No label saying "delegation"; the shape says it. A refused
  handoff shows an ✕ instead of an arrow and names the reason (`would loop`,
  `depth limit`).
- **Report** — what the agent actually said, in a tinted panel in that agent's ink. The
  only full-width prose in the feed, so the human sentences stand out from the
  instrument readings around them.
- **Milestone** — the run starting and stopping, and desk decisions. Carries small
  stamps for the stop reason and the usage: `completed`, `54,251 tokens · 27 tool
  calls`.

Timestamps run down a fixed left gutter in tabular mono, so the column is a straight
edge and the eye can use it as a ruler.

New lines **ink in** — a 420ms fade up through a slight blur, as though the ink is
settling into paper. The feed follows the conversation while the run is live and stops
following the moment it finishes, because nothing is more annoying than a log that
yanks you back to the bottom while you are reading the middle of it.

---

## 4. How resolved tickets are displayed

A resolved ticket should read as *finished business* without disappearing — the desk
should still show the day's work.

Four changes, together:

1. The **chip** turns green and gains a stamp mark.
2. The card drops to the sunk paper colour and **loses its shadow**, so it sits flat
   against the rail while open tickets lift off it.
3. Subject and requester soften to the tertiary ink — present, no longer demanding.
4. A faint **diagonal hatch** is laid over the card. It is the "filed" texture you get
   from a rubber stamp or a struck-through docket, at 4.5% opacity so it registers
   peripherally rather than competing with the text.

The board header carries a running count — **`2/3 done`** — so progress is readable
without comparing cards.

### What "resolved" actually means here

Worth saying plainly, because it shaped the UI. **The agents do not resolve tickets.**
A run usually ends in `waiting_approval` or `blocked`, because a correct plan is not a
finished job — the customer still has no tee and the rent is still unpaid.

So the dashboard shows the real status the boss set, and adds a **Mark resolved**
control for the person. It is disabled while anything on that ticket is still queued
for their decision, and the backend refuses it too: a ticket cannot be finished while
the shop is waiting on a signature. Five statuses get their own chip — `open`,
`in progress`, `waiting approval`, `blocked`, `resolved` — because flattening them to
done/not-done would hide the distinction between *stuck* and *waiting on you*, which is
the most useful thing the board can tell someone.

---

## 5. How cash and balance are displayed

Money appears in two places, deliberately.

**In the counter, always.** The checking balance sits top right in the ledger mono at
1.5rem, visible from every scroll position. It is the number that constrains everything
the shop can do, and it should never require looking for.

**In the till panel**, as a three-line ledger:

| | |
|---|---|
| In checking | $3,400.00 |
| Queued for approval | −$2,400.00 |
| Free to spend | $1,000.00 |

The middle row is the one that matters and it is set in the hold amber. Two payments
that each fit the balance may not fit *together*, and a dashboard that showed only
`balance` would invite exactly that mistake. The panel says so in a note underneath,
along with the fact that no revenue is modelled — this number only ever falls.

All figures are **Roboto Mono with tabular numerals**, so digits line up down a column
and `$3,400.00` and `$1,000.00` are the same width. Monospace here is for measurement,
not for a technical costume.

### The one authored moment

When an approved payment clears, the counter balance **settles**: it flashes to the go
green, lifts two pixels, takes a brief glow, and sinks back to ink over 1100ms on an
exponential ease-out. It fires only on a real change, not on every poll.

This is the only decorative animation in the application, and it earns its place —
money leaving the shop is the single most consequential event on this page, and it
happens in a corner the user may not be looking at when they click. A balance that
changed silently would be the wrong thing to be quiet about.

---

## 6. Reasoning behind the design choices

**Warm paper, not a dark console.** Picked from the use scene, not the category. This
is a shop in daylight; an "ops dashboard" dark theme would be a costume. The ground is
`#f6f3ec` with a fixed 3px dot grain at 40% opacity — fixed rather than scrolling, so
the paper stays still while panels move over it.

**Three type voices, each with a job.** Newsreader (variable serif) for headings and
anything a person wrote — ticket subjects, the boss's decision, drafted messages.
Inter for interface text. Roboto Mono, tabular, for every figure and every tool name.
The rule is simple enough to hold: *serif for judgment, sans for the interface, mono
for measurement.* All three are self-hosted via `@fontsource-variable` — no network
request at runtime and no layout shift.

**The ticket's own words are quoted, not summarised.** `"Needs a tee in size S."` sits
in a sunk panel under the subject. Everything else on the page is the shop's
interpretation; this is the only primary source, and it should look like one.

**The decision is a structured sheet, not a paragraph.** The boss returns a
`TicketDecision`, and the page renders its parts separately: the decision, the
rationale, who did what, what changed in the shop, what they found (each finding with
the tool it came from), and — in its own section with amber marks — **what they could
not establish**. Surfacing the unknowns is a design choice with a point: an agent that
admits a gap is more useful than one that reads smoothly, and burying that section
would quietly punish honesty.

**Per-agent summaries are computed from the trail, not from the boss's prose.** The
boss names who it consulted; the audit trail knows what each of them actually called.
Those are not always the same thing, and the trail is the one that cannot flatter
itself.

**Refusals are shown in the shop's own words.** When the backend declines — "A human
must approve a payment before it can be made", "that would overdraw the account" — the
dashboard prints that sentence. It is the rule talking, and it teaches the operator the
system's constraints better than "Error 409" ever would.

**Depth is offset plus blur.** Three shadow levels, all with a real offset and a soft
blur. No zero-offset halos, which read as decoration rather than elevation. Open
tickets lift; resolved ones lie flat. The lift *is* the status signal.

**The browser's own surfaces are themed.** Selection is brass-tinted, the caret is
brass, scrollbars are rule-coloured with a paper-coloured inset border, focus rings are
navy at a 2px offset. These are the parts nobody draws, and leaving them at their
defaults is the cheapest way for a page to look assembled rather than built.

**Contrast was measured, not estimated.** Every text colour was checked by computed
style against its *actual* rendered background, including nested ones. The first pass
found `--ink-3` at 4.10:1 against the sunk rail ground — fine on the main paper, short
on the rails, which is where most of it lives. It was darkened to `#5f6775` (4.75:1 on
the darkest ground it ever touches). The rule I settled on: measure a token against the
darkest surface it sits on, not the most flattering one.

---

## 7. The details that make it pleasant to use

- **Polling matches attention.** 1.5s for the event feed and 2.5s for the desk while
  the team is out; 15s when the desk is quiet. Overlapping requests are skipped rather
  than queued, so a slow response cannot make the feed jump around.
- **A breathing dot** next to "Team is working…" — a 1.5s ease pulse. One small sign of
  life during the thirty seconds where nothing else can change.
- **The approver's name is a field, not a hidden default.** It sits directly above the
  Approve button and the button is disabled while it is empty. The name is written into
  `payments.approved_by`, and the form should say so by its shape.
- **The approve button names its action**: *Approve & pay* for a payment, *Approve &
  order* for a purchase order. Not "Confirm".
- **Drafts are marked “Not sent”** with a quill mark. The shop never sends anything, and
  the card should not let anyone assume otherwise even for a moment.
- **Every empty state is a sentence, not a shrug.** "Nothing to approve. The agents can
  queue a payment, but only you can make one." The empty state is where a user learns
  what the panel is for.
- **The run button explains the boundary before you press it**: "The team can read the
  shop and prepare a payment. It cannot spend anything — that needs you."
- **Loading is shimmer-skeleton shaped like the content**, not a spinner, so the layout
  does not jump when data lands.
- **Keyboard and screen readers are real.** The board is a `<nav>` of buttons with
  `aria-current`; the selected ticket is announced. Banners carry `role="alert"` and
  `role="status"`. Every icon is `aria-hidden` with the meaning in adjacent text.
  `prefers-reduced-motion` turns off the settle, the ink-in, and the pulse.
- **The failure case is useful.** If the backend is not running, the dashboard says
  exactly what to type: `cd backend && uvicorn main:app --reload --port 8000`.

---

## 8. Running it

```bash
# backend — from the project root
cd backend && uvicorn main:app --reload --port 8000

# frontend — from the project root
cd frontend && npm install && npm run dev
```

The dashboard is at `http://localhost:5173` and calls the backend at
`http://localhost:8000`, which lists the dev-server origins in its CORS middleware.
Point it elsewhere with `VITE_API_BASE`; see `frontend/.env.example`.
