# Campus Customs — Multi-Agent Operations

MGT 409, Homework 5. A five-agent team that works the open tickets at a Yale apparel
shop on Chapel Street: an MCP server over the shop database, a FastAPI backend running
the agents, and a React dashboard where a person watches them work and approves
anything that costs money.

**Agents never move money.** They can read the shop and prepare a payment or an order;
a human clicking Approve is what debits the account, and their name is written into
`payments.approved_by`. That boundary is enforced in the tools, not in the prompts —
`decide_approval` is in no agent's toolset.

Every agent runs on **`gpt-6-luna`** through Portkey. No other model appears in the
code or in any recorded run.

---

## Setup

Python 3.12+ and Node 20+.

```bash
# 1. Python environment
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 2. Your Portkey key
cp .env.example .env          # then edit .env and paste your key in
#   PORTKEY_API_KEY=...
#   A file named PORTKEY_API_KEY.env at the project root works too.

# 3. Frontend dependencies
cd frontend && npm install && cd ..
```

The app starts without a key — the dashboard, the board and the till all work. Only
the agent team needs one, and the Run button says so when it is missing.

---

## Copy the original database to the working database

The shop ships with two files. **`data/campus_customs.db` is the original and is never
written to** — it is the reset point. Everything runs against a working copy:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

Both files are committed, so a fresh clone already has a working copy at the opening
state: three open tickets, $3,400.00 in checking, invoice 501 open and three days
overdue against the shop's date of 2026-08-31.

---

## Start the MCP server

```bash
.venv/bin/python mcp_server/server.py
```

It serves over stdio and points at `data/campus_customs_new.db`, resolved from its own
file location so it opens the working copy whichever directory you launch from.

**You usually do not need to run this yourself.** The backend starts it as a
subprocess, and `.mcp.json` at the project root lets Claude Code attach to it when a
session opens in this folder. Run it directly only to check that it starts.

To exercise all eighteen tools against the configured server and re-check every value
with independent SQL:

```bash
.venv/bin/python scripts/mcp_smoke.py
```

---

## Start the FastAPI backend

From the `backend/` directory, as the assignment specifies:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Serves at `http://localhost:8000`, with interactive docs at `/docs` and a wiring check
at `/api/health`. The backend never opens the database itself — every figure comes
back through the MCP server, the same door the agents use.

---

## Start the React frontend

From the `frontend/` directory:

```bash
cd frontend
npm run dev
```

Serves at `http://localhost:5173` and calls the backend at `http://localhost:8000`,
which lists the dev-server origins in its CORS middleware. Override the backend host
with `VITE_API_BASE` if you need to; see `frontend/.env.example`.

---

## Reset the database before running all three tickets

Reset first, so the run starts from the shop's opening state. Either way works:

```bash
# from the dashboard
click "Reset the shop" in the top right

# or from the command line
cp data/campus_customs.db data/campus_customs_new.db

# or against a running backend
curl -X POST http://localhost:8000/api/reset
```

A reset restores the three open tickets and the $3,400.00 balance, and clears the
approval queue, placed orders and drafts. **It does not clear `output/audit_trail.json`**
— the trail is append-only across resets by design, and there is no tool an agent can
reach that would erase the record of what it did.

Then, on the dashboard: pick a ticket, press **Call the team in**, watch the feed, and
approve or reject anything that lands in **Waiting on you**. Some tickets need more
than one pass — ticket 101 cannot order the tee until the invoice blocking the vendor
has been paid.

---

## What is in here

| | |
|---|---|
| `mcp_server/` | FastMCP server, 18 tools over the shop database. See its [README](mcp_server/README.md). |
| `backend/` | FastAPI app and the five PydanticAI agents. One prompt file per agent in `backend/prompts/`. |
| `frontend/` | React + Vite + TypeScript dashboard. |
| `data/` | The original database and the working copy. |
| `output/` | Everything the assignment asks to be produced — see below. |
| `scripts/` | Test and evidence scripts. |
| `.mcp.json` | Project-scoped MCP configuration, read by Claude Code at session start. |

### Output

| File | |
|---|---|
| [`harness.md`](output/harness.md) | The full write-up: tables, tools, agents, routes, dashboard, safety, limits, and the live run. |
| [`design.md`](output/design.md) | The dashboard's design rationale. |
| [`desk_tickets.html`](output/desk_tickets.html) | The plan written before the agents ran, beside what actually happened. Cash ledger and reflection. |
| [`resolved_board.html`](output/resolved_board.html) | The dashboard after each ticket was resolved. |
| [`resolved_tickets.json`](output/resolved_tickets.json) | Per ticket: status, outcome, each agent's contribution, every human approval. |
| [`mcp_smoke.json`](output/mcp_smoke.json) | MCP tool evidence, every value re-checked against SQL. |
| [`audit_trail.json`](output/audit_trail.json) | Every agent step ever taken, appended, never truncated. |
| `github_url.txt` | This repository's URL. |

Both HTML pages open by double-clicking; they need no server.

### Tests

```bash
.venv/bin/python scripts/mcp_smoke.py          # the MCP tools, through .mcp.json
.venv/bin/python scripts/test_shop_rules.py    # the shop rules, enforced in tool code
.venv/bin/python scripts/test_agent_team.py    # team, model lock, loop guards, trail
.venv/bin/python scripts/test_routes.py        # every backend route (server must be up)
```

`test_agent_team.py --offline` and `test_routes.py --offline` skip the live model calls.
The first three reset the working copy before and after, so a test never leaves the
shop half-worked.

---

## The shop's rules, and where each one is enforced

| Rule | Enforced by |
|---|---|
| A human approves every payment and every purchase order | `decide_approval` is in no agent's toolset; `roles.assert_no_agent_can_approve()` raises at import if that changes |
| Never a negative balance | `record_payment` re-reads the balance inside the transaction and refuses |
| A vendor will not ship while it holds an open invoice | checked when an order is requested and again when it is placed |
| "Today" is `desk.date_today`, not the real date | `db.today()` is the only date source |
| Nothing is sent to anyone | `draft_customer_message` writes to the board; there is no send path |
| Never invent a fact | tools refuse unknown SKUs, sizes, accounts and tickets by name rather than returning zero |

---

## Notes for a grader

- `.env` is **not** committed. `.env.example` has the placeholder. The agents need
  `PORTKEY_API_KEY`; everything else runs without it.
- The original `data/campus_customs.db` has not been modified at any point
  (sha1 `f447ca6a2766a90f3c1f81215c8f774ab109ea4c`).
- `data/campus_customs_new.db` is committed **at the opening state**, so a clone is
  ready for a clean run.
- The recorded run of all three tickets took seven passes and ended at **$160.00**,
  matching `cash_accounts` exactly. The ledger and the reconciliation are in the Cash
  tab of `desk_tickets.html`; what went wrong on the way is in the Reflection tab.
