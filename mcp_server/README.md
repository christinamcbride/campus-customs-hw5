# Campus Customs MCP Server

## What it is for

This is the shared tool surface for the Campus Customs agent team. The boss,
inventory, accounting, facilities, and customer service agents all reach the shop's
data through this one server rather than querying the database themselves.

Keeping it in one place buys two things. The shop's rules — human approval before any
payment, no negative cash balance, no shipment from a vendor holding an open invoice —
are enforced in tool code, where the schema cannot enforce them. And because every
agent goes through the same door, there is a single record of what the team actually
looked at before it decided anything.

The tools never estimate. If a SKU is not stocked in the size asked for, the tool says
so instead of returning zero, because "we do not carry it" and "we are out of it" are
different answers to a customer.

## Which database it uses

`data/campus_customs_new.db` — the working copy.

The original `data/campus_customs.db` is the reset point and is never opened for
writing. To put the shop back to its starting state before a full ticket run:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

The path is resolved relative to this file, so the server can be started from any
directory. If the working copy is missing, the server says exactly which command to
run rather than silently creating an empty database.

## Which tools it provides

Eighteen tools. Every shop fact any agent knows arrives through one of them — there is
no second data layer and no agent opens the database directly.

### Reading the shop

| Tool | Reads | Answers |
|---|---|---|
| `list_tickets` | `tickets` | What is on the board, filtered by status. |
| `get_ticket` | `tickets` | One ticket in full, including the requester's own words. |
| `check_stock` | `inventory`, `desk` | Units on hand for one SKU and size, and the shortfall against a requested quantity. |
| `check_rent_due` | `leases`, `desk` | Rent owed per lease and days until due. |
| `check_discount_margin` | `pricing` | Cost, list price, break-even, and what a proposed price does to the margin. |
| `list_vendors` | `vendors`, `invoices`, `desk` | Lead times, and `will_ship`, which is false when an unpaid invoice is blocking them. |
| `list_invoices` | `invoices`, `vendors`, `desk` | Amounts and how overdue each one is. |
| `get_cash_balance` | `cash_accounts`, `approvals`, `desk` | The balance, what is already queued against it, and what is really free. |
| `list_approvals` | `approvals` | Requests waiting on a human, and what was decided. |
| `list_purchase_orders` | `purchase_orders` | Restocks already ordered, with arrival dates. |
| `list_message_drafts` | `message_drafts` | Customer messages drafted so far. |

### Changing the shop

| Tool | Writes | Rule it enforces |
|---|---|---|
| `update_ticket` | `tickets` | A note is required, statuses are a fixed set, and notes are appended rather than overwritten. |
| `request_payment_approval` | `approvals` | Pays nothing. The amount must match what is actually owed, and it is refused if the account cannot cover it. |
| `request_purchase_order_approval` | `approvals` | Orders nothing. Refused if the vendor is blocked by an open invoice. Unit cost comes from `pricing`. |
| `record_payment` | `cash_accounts`, `payments`, `invoices`/`leases`, `approvals` | Refuses unless a human approved it. Re-reads the balance and refuses rather than going negative. One transaction. |
| `place_purchase_order` | `purchase_orders`, `approvals` | Refuses unless a human approved it. Re-checks the vendor hold. Does **not** touch inventory — the shelf changes on delivery. |
| `draft_customer_message` | `message_drafts` | Saves to the board. Nothing is ever sent. |

### The human's tool

| Tool | |
|---|---|
| `decide_approval` | Approve or reject a queued request. **Given to no agent.** The dashboard calls it on behalf of the person at the desk, and `decided_by` records their name. This omission, not a sentence in a prompt, is what makes "a human approves every payment" true. |

### Tables added to the working copy

The original schema has nowhere to park a payment awaiting a human, nowhere to record
goods on order, and nowhere to hold a drafted message. Three tables fill those gaps and
are created on demand in the **working copy only**: `approvals`, `purchase_orders`, and
`message_drafts`. Resetting the shop clears them along with everything else, which is
the behaviour we want — a reset should not leave a stale approval queue behind.

## Running it

```bash
.venv/bin/python mcp_server/server.py
```

It serves over stdio, which is how the backend will attach to it.

## Files

| File | |
|---|---|
| `server.py` | The FastMCP instance and the tool definitions. |
| `db.py` | Connection to the working copy, plus the `desk.date_today` lookup. |

## Connecting it to Claude Code

The project root holds a `.mcp.json`, which is the project-scoped MCP configuration
Claude Code reads when a session starts in this folder:

```json
{
  "mcpServers": {
    "campus-customs-ops": {
      "type": "stdio",
      "command": ".venv/bin/python",
      "args": ["mcp_server/server.py"],
      "env": {}
    }
  }
}
```

The paths are relative to the project root, so the file works on any machine that has
created the virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Claude Code reads `.mcp.json` at session start and asks once whether to trust a
project server, so a session already running when the file was created has to be
restarted before the tools appear. The three tools then show up as
`check_stock`, `check_rent_due`, and `check_discount_margin`.

## Testing it

```bash
.venv/bin/python scripts/mcp_smoke.py
```

This launches the server as a real stdio subprocess using the exact `command` and
`args` from `.mcp.json`, calls all three tools, and re-checks every value they return
against an independent SQL query on the working copy. It writes the captured run to
`output/mcp_smoke.json` and exits non-zero if anything fails to match. Nothing in that
evidence file is written by hand.
