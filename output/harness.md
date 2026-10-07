# Campus Customs Multi-Agent Operations — Harness

Working notes for the agent team that runs the shop on Chapel Street: what the data
holds, what the agents can do, what stops them doing the wrong thing, and what happened
when all three tickets were actually worked.

Built up across the assignment, so it reads in the order the system was understood —
the database first, then the tools over it, then the agents using the tools, then the
desk a person sits at.

| | Where |
|---|---|
| The database tables | §2, with §1 on the original-versus-working copy and §4 on what the schema does not provide |
| The MCP tools | §5 (the first three) and §8 (all eighteen, with the table each one reads) |
| All five agents | §7 |
| The backend API routes | §13 |
| The frontend dashboard | §14, with the full design rationale in [`design.md`](design.md) |
| The safety rules | §9, with the loop and token ceilings in §10 and the audit trail in §11 |
| What actually happened | §15 — the live run of all three tickets, and the cash |

---

## 1. The two databases

| File | Role |
|---|---|
| `data/campus_customs.db` | The original. **Never written to.** It is the reset point. |
| `data/campus_customs_new.db` | The working copy. The MCP server and backend point here. |

The copy was made with `cp` and verified byte-identical
(`sha1 f447ca6a2766a90f3c1f81215c8f774ab109ea4c`, 53,248 bytes each).

To reset the shop to its original state before a full ticket run:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

**Structural notes.** Nine tables, no views and no triggers. The only indexes are the
three SQLite creates automatically for the text primary keys on `cash_accounts`,
`inventory`, and `pricing`. Foreign keys are *declared* on `invoices` and `tickets`, but
SQLite does not enforce them unless `PRAGMA foreign_keys = ON` is set per connection —
so the tools must not assume a bad `vendor_id` or `invoice_id` will be rejected by the
database. There are no `CHECK` constraints either: nothing at the storage layer stops a
negative cash balance. **Every invariant in the shop rules has to be enforced in tool
code.**

---

## 2. The tables

### `desk` — 1 row

| Field | Type | Value |
|---|---|---|
| `date_today` | TEXT NOT NULL | `2026-08-31` |
| `notes` | TEXT | *(empty)* |

*Why it matters:* this is the shop's clock. Every "is it overdue?" question —
invoices, rent, vendor lead times — is measured against this date, not the real
calendar, so agents must read it rather than call `date.today()`.

---

### `tickets` — 3 rows, all `open`

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `type` | TEXT NOT NULL | seen: `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT NOT NULL | a customer, a landlord, or a student org |
| `subject` | TEXT NOT NULL | one-line summary |
| `sku` | TEXT | nullable — only product tickets carry one |
| `size` | TEXT | nullable |
| `qty` | INTEGER | nullable |
| `lease_id` | INTEGER → `leases.id` | nullable |
| `invoice_id` | INTEGER → `invoices.id` | nullable |
| `status` | TEXT NOT NULL | all three are `open` |
| `notes` | TEXT | the human-written ask |
| `created_at` | TEXT NOT NULL | ISO-8601 with `-04:00` offset |

*Why it matters:* this is the board. It is the agent team's work queue and the only
table that says what the shop has been asked to do; the boss agent reads it to route
work, and closing a ticket is how a run makes progress.

The nullable `sku` / `lease_id` / `invoice_id` columns are the routing signal: which
columns are filled tells the boss which domain a ticket belongs to.

---

### `inventory` — 10 rows

| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT | composite PK with `size` |
| `name` | TEXT NOT NULL | display name, repeated per size |
| `size` | TEXT | `S`/`M`/`L`/`XL`, or `OS` for one-size goods |
| `qty` | INTEGER NOT NULL | units on hand |
| `location` | TEXT NOT NULL | aisle in the shop |

*Why it matters:* the inventory agent answers "can we fill this order?" from here, and
it is the table a fulfilled order or a received restock has to decrement or increment.

Current stock:

| SKU | Name | S | M | L | XL | OS | Aisle |
|---|---|---|---|---|---|---|---|
| `CC-HOOD-NAVY` | Basic Hoodie Big Yale | 4 | 8 | 14 | 6 | — | A |
| `CC-TEE-WHITE` | Classic Bulldog Tee | **0** | 5 | 3 | 2 | — | B |
| `CC-HAT-BLUE` | Yale Cap | — | — | — | — | 40 | C |
| `CC-MUG-CREST` | Crest Mug | — | — | — | — | **0** | D |

Two zero rows, and one of them (`CC-TEE-WHITE` / S) is exactly what ticket 101 asks for.

---

### `pricing` — 4 rows, one per SKU

| Field | Type | |
|---|---|---|
| `sku` | TEXT PK | |
| `unit_cost` | REAL NOT NULL | what the shop pays |
| `list_price` | REAL NOT NULL | what the shop charges |

*Why it matters:* the accounting agent needs it to check whether a discount request
still clears cost, and to price a purchase order before asking for approval.

| SKU | Unit cost | List | Gross margin |
|---|---|---|---|
| `CC-HOOD-NAVY` | $22.00 | $58.00 | $36.00 (62.1%) |
| `CC-TEE-WHITE` | $8.00 | $28.00 | $20.00 (71.4%) |
| `CC-HAT-BLUE` | $6.00 | $22.00 | $16.00 (72.7%) |
| `CC-MUG-CREST` | $3.50 | $14.00 | $10.50 (75.0%) |

---

### `vendors` — 3 rows

| Field | Type | |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `specialty` | TEXT NOT NULL | free text, not an enum |
| `lead_days` | INTEGER NOT NULL | days from order to arrival |

*Why it matters:* when stock is short, the inventory agent picks a vendor from here,
and `lead_days` is the only input to a promised restock date.

| id | Name | Specialty | Lead days |
|---|---|---|---|
| 1 | Bulldog Print Co | apparel reprint | 5 |
| 2 | Elm City Gifts | mugs and small goods | 3 |
| 3 | QuickShip CT | local courier | 1 |

Only vendor 1 does apparel, so both apparel tickets funnel to the one vendor the shop
currently owes money to. That is not a coincidence in the data; it is the squeeze.

---

### `leases` — 1 row

| Field | Type | Value |
|---|---|---|
| `id` | INTEGER PK | 1 |
| `space_name` | TEXT NOT NULL | Chapel Street shop |
| `landlord` | TEXT NOT NULL | Elm City Properties |
| `monthly_rent` | REAL NOT NULL | $2,400.00 |
| `next_due` | TEXT NOT NULL | `2026-09-02` |
| `notes` | TEXT | *(empty)* |

*Why it matters:* the facilities agent works from this row — it is the whole shop-space
side — and `monthly_rent` is the largest single claim on the shop's cash.

---

### `cash_accounts` — 1 row

| Field | Type | Value |
|---|---|---|
| `name` | TEXT PK | checking |
| `balance` | REAL NOT NULL | $3,400.00 |
| `date` | TEXT NOT NULL | `2026-08-31` |

*Why it matters:* this is the hard ceiling on everything the team can do. No revenue is
modeled, so this number only falls, and the payment tool must refuse any request that
would push it below zero.

---

### `invoices` — 1 row

| Field | Type | Value |
|---|---|---|
| `id` | INTEGER PK | 501 |
| `vendor_id` | INTEGER NOT NULL → `vendors.id` | 1 (Bulldog Print Co) |
| `amount` | REAL NOT NULL | $840.00 |
| `due_date` | TEXT NOT NULL | `2026-08-28` |
| `status` | TEXT NOT NULL | `open` |
| `description` | TEXT | Rush reprint CC-TEE-WHITE S |

*Why it matters:* an open invoice is both a bill and a blocker — the shop rule says a
vendor will not ship while one is outstanding, so this row gates restocking as well as
cash.

Against `desk.date_today` of 2026-08-31, invoice 501 is **3 days overdue**.

---

### `payments` — 0 rows

| Field | Type | |
|---|---|---|
| `id` | INTEGER PK | |
| `kind` | TEXT NOT NULL | what is being paid (e.g. an invoice vs. rent) |
| `ref_id` | INTEGER | the invoice or lease the payment settles — nullable, and **not** a declared foreign key, so `kind` is what disambiguates which table `ref_id` points into |
| `amount` | REAL NOT NULL | |
| `account` | TEXT NOT NULL | pairs with `cash_accounts.name` |
| `paid_at` | TEXT NOT NULL | |
| `approved_by` | TEXT NOT NULL | |

*Why it matters:* this is the audit trail for money leaving the shop, and
`approved_by` being `NOT NULL` means the schema itself refuses to record a payment that
nobody approved.

The table is empty, so the exact vocabulary for `kind` is not given by the data. I will
define it when the payment tool is built rather than guess now.

---

## 3. The three open tickets, and how they interlock

### Ticket 101 — customer order, Tauhid Zaman
> Bulldog tee, `CC-TEE-WHITE`, size S, qty 1. *"Needs a tee in size S."*
> Carries `invoice_id = 501`.

`inventory` has **0** of that SKU/size, so it cannot be filled off the shelf. The linked
invoice is the reprint that was already ordered to cover exactly this gap —
*"Rush reprint CC-TEE-WHITE S"* — but it is unpaid and overdue, so under the shop rule
Bulldog Print Co will not ship. The ticket is blocked on money, not on stock.

### Ticket 102 — rent notice, Elm City Properties
> Lease 1. *"Email: shop rent due in 2 days."*

Matches `leases.next_due = 2026-09-02`, two days after the desk date. $2,400 — not yet
overdue, but the largest claim on the account.

### Ticket 103 — price override, Yale AI Club
> 20 × `CC-HOOD-NAVY`, size M, asking for a bulk discount.

Only **8** are on hand, a shortfall of **12**. Restocking apparel means vendor 1 again
— the same vendor blocked by invoice 501 — at 5 lead days, so the earliest arrival is
2026-09-05 *if the invoice is cleared first*. Separately, the discount itself is an
accounting question against the $22 cost / $58 list line.

### The chain

```
          invoice 501 ($840, overdue)  ──blocks──►  Bulldog Print Co (vendor 1)
                 │                                          │
             must be paid                          only apparel vendor
                 │                                    ╱            ╲
                 ▼                                   ▼              ▼
          cash: checking $3,400        ticket 101 (tee S, 0 on hand)   ticket 103 (12 hoodies short)
                 │
                 └──────────► ticket 102 (rent $2,400, due 2026-09-02)
```

Both product tickets run through one vendor, that vendor is blocked by one invoice, and
that invoice competes with rent for one pot of cash. The arithmetic:

| | Amount |
|---|---|
| Checking balance | $3,400.00 |
| Invoice 501 | −$840.00 |
| Rent (lease 1) | −$2,400.00 |
| **Remaining** | **$160.00** |

Both obligations fit, with $160 left over — but only both, and only in that order if
the shop wants the tee to ship. Anything else the team decides to buy (a purchase order
for 12 hoodies at $22 = $264, say) does **not** fit afterward. That is the real decision
the boss agent has to make, and every piece of it needs human approval.

---

## 4. Things the schema does not give us

Noting these now so later problems handle them deliberately rather than by accident:

- **No purchase-order table.** There is nowhere to record "12 hoodies ordered, arriving
  2026-09-05." Either a received restock is written straight into `inventory.qty`, or a
  table is added. To be decided when the restock tool is built.
- **No pending-approval state.** `payments` records approved payments only; there is no
  column for "requested, awaiting human." The approval queue therefore has to live
  outside this table.
- **No per-ticket history.** `tickets` has one `status` and one `notes`; there is no
  place for agent reasoning or drafted customer messages. The dashboard will need its
  own store for that.
- **`cash_accounts.date` is not a ledger.** One row, one balance. Any balance history
  has to be reconstructed from `payments`.

---

## 5. The MCP server

`mcp_server/` holds a FastMCP server pointed at `data/campus_customs_new.db`. It is the
single door the whole agent team uses to reach shop data — the boss, inventory,
accounting, facilities, and customer service agents call these tools rather than
querying SQLite themselves, so the shop's rules live in one enforceable place and there
is one record of what the team looked at.

Three tools so far, one per open ticket. All three are read-only; the tools that move
money or change stock come in later problems.

### `check_stock(sku, size, quantity_requested)`

- **Reads:** `inventory` for the quantity and aisle, `desk` for the as-of date.
- **Unlocks ticket:** **101** — Tauhid Zaman's order for one `CC-TEE-WHITE` in size S.
- **Why it is the right tool:** ticket 101 names a specific SKU and size and asks the
  shop to hand over one unit, so the first thing that has to be established is that the
  shelf holds **0** of that exact row — which is what turns a routine order into a
  restock problem and sends the ticket to the inventory agent instead of straight to
  fulfilment.

It returns `shortfall` rather than only a yes/no, so the same call also sizes the gap
on ticket 103 (20 hoodies wanted, 8 on hand, shortfall 12). A SKU/size pair that is not
in the table raises an error listing the sizes actually carried, because "we do not
carry XXL" and "we are out of XXL" are different answers to give a customer.

### `check_rent_due(lease_id)`

- **Reads:** `leases` for the amount and due date, `desk` for the shop's date.
- **Unlocks ticket:** **102** — Elm City Properties' notice that rent is due in 2 days.
- **Why it is the right tool:** ticket 102 arrives as an email claim with no figures in
  it, carrying only `lease_id = 1`, so the facilities agent has to turn that pointer
  into the shop's own record — $2,400 against the Chapel Street lease, due 2026-09-02
  — and confirm the landlord's "2 days" against `desk.date_today` rather than taking
  the sender's word for the timing.

`days_until_due` goes negative once a payment is late, so the same tool answers "is
this overdue?" without a second call. It reports what is owed and pays nothing — rent
leaves the account only through the payment tool, and only after a human approves it.

### `check_discount_margin(sku, quantity, proposed_unit_price)`

- **Reads:** `pricing`.
- **Unlocks ticket:** **103** — the Yale AI Club's request for a bulk discount on 20
  size-M hoodies.
- **Why it is the right tool:** ticket 103 asks for a discount but names no price, so
  the accounting agent cannot answer until it knows the $22 cost against the $58 list
  — this tool supplies the break-even floor and scores any figure the shop is
  considering, which is the difference between negotiating from the margin and
  guessing at one.

Called without a `proposed_unit_price` it gives the list-price position and the
break-even floor; called with one it adds the discount off list, the per-unit margin,
and `covers_unit_cost`, which goes false below $22. It scores the number. It does not
approve it — that is the boss agent's call, after accounting reports.

### What is deliberately not here yet

The sharpest fact in the dataset has no tool: invoice 501 is $840 open and 3 days
overdue to Bulldog Print Co, and under the shop rule that vendor will not ship while it
stands — which blocks the restock on **both** 101 and 103. A `check_vendor_hold` tool
over `invoices` + `vendors` belongs with the payment and purchase-order tools, since
clearing the hold and paying the bill are the same action. Noting it here so the gap is
a decision rather than an oversight.

### Verified

All three tools were exercised in-process against the working copy. `check_stock`
returned 0 on hand for `CC-TEE-WHITE`/S and a shortfall of 12 for `CC-HOOD-NAVY`/M at
qty 20; `check_rent_due` returned $2,400 due 2026-09-02 with `days_until_due = 2` and
`is_overdue = false`; `check_discount_margin` returned 62.07% at list for the hoodie,
52.59% at a proposed $46.40, and a negative margin with `covers_unit_cost = false` at
$18.00. Unknown SKUs, unstocked sizes, and a missing lease id each raised a specific
error instead of a made-up answer. The database was unchanged by the run.

---

## 6. Connecting and testing the MCP server

### Configuration

`.mcp.json` at the project root is the project-scoped configuration Claude Code reads
when a session opens in this folder:

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

Both paths are relative to the project root, so the file works on any machine that has
run `python3 -m venv .venv` and installed `requirements.txt` — no absolute path from my
laptop is baked into the repository. The server name `campus-customs-ops` matches the
`FastMCP(name=...)` in `server.py`.

The database path is not in this config on purpose. `mcp_server/db.py` resolves
`data/campus_customs_new.db` from its own file location, so the server opens the
working copy no matter which directory it is launched from, and there is no setting
anyone can point at the original by mistake.

The startup banner is suppressed (`mcp.run(transport="stdio", show_banner=False)`)
because stdio is the protocol channel.

### Test evidence

`scripts/mcp_smoke.py` writes `output/mcp_smoke.json`. It launches the server as a real
stdio subprocess using the exact `command` and `args` read out of `.mcp.json` — not an
in-process import, which could pass while the real configuration is broken — then calls
each tool and re-checks every returned value with an independent SQL query against the
working copy. Nothing in the evidence file is typed by hand; it is all captured from the
run, and the script exits non-zero if any value fails to match.

| Ticket | Tool | Request tested | Fields checked | Result |
|---|---|---|---|---|
| 101 | `check_stock` | "Do we have one CC-TEE-WHITE in S, and if not how short are we?" | 6 | all match |
| 102 | `check_rent_due` | "What does our lease record say we owe, and when is it due against the shop's date?" | 7 | all match |
| 103 | `check_discount_margin` | "Our cost and list on 20 navy hoodies — would $46.40 a unit still clear cost?" | 10 | all match |

Key values confirmed against the database: tee S at **0 on hand** in Aisle B with a
shortfall of 1; rent **$2,400** due **2026-09-02**, `days_until_due = 2` measured from
`desk.date_today` rather than the real calendar; hoodie **$22 cost / $58 list**,
62.07% margin at list, 52.59% at the proposed $46.40, `covers_unit_cost = true`.

Only `unit_cost` and `list_price` are stored for the hoodie — every other figure in
that tool's output is arithmetic over those two columns, so the script recomputes each
one from the raw row. That is the check that would catch a tool inventing a margin.

### Honest-answer checks

A tool that quietly returns `0` for an item the shop does not carry is inventing data,
so four inputs with no row behind them were tried. All four were refused with a
specific message rather than answered:

| Input | Refusal |
|---|---|
| `check_stock` CC-TEE-WHITE / XXL | "not stocked in size XXL. Sizes carried: L, M, S, XL." |
| `check_stock` CC-SCARF-NAVY / OS | "There is no SKU 'CC-SCARF-NAVY' in the inventory table." |
| `check_rent_due` lease 99 | "There is no lease with id 99." |
| `check_discount_margin` CC-SCARF-NAVY | "There is no pricing row for SKU 'CC-SCARF-NAVY'." |

The first is the one that matters most for ticket 101: "we do not carry it" and "we are
out of it" are different answers to give a customer, and a tool that collapses them
would hand the customer service agent a lie to draft from.

### Database integrity

The script hashes both database files before and after the run. All three tools are
read-only, so both must be unchanged:

| File | Before | After | |
|---|---|---|---|
| `data/campus_customs_new.db` | `f447ca6a…` | `f447ca6a…` | unchanged |
| `data/campus_customs.db` | `f447ca6a…` | `f447ca6a…` | untouched |

---

## 7. The agent team

Five PydanticAI agents, all on `gpt-6-luna` through Portkey, sharing one MCP
connection. Built in `backend/team.py` from the role registry in `backend/roles.py`;
each agent's full instructions live in its own file under `backend/prompts/`.

### The five agents

| Agent | Responsible for | MCP tools it holds | Output |
|---|---|---|---|
| **boss** | Reading the ticket, deciding who should work it, weighing competing claims on the shop's one cash account, making the final call, and owning the board. | `get_ticket`, `list_tickets`, `update_ticket`, `get_cash_balance`, `list_approvals`, `list_purchase_orders`, `list_message_drafts` | `TicketDecision` |
| **inventory** | Stock by SKU **and size**, the shortfall against what was asked for, which vendor could restock it, lead times, and whether a vendor hold is in the way. | `check_stock`, `list_vendors`, `list_invoices`, `request_purchase_order_approval`, `place_purchase_order`, `list_purchase_orders`, `list_approvals`, `get_ticket` | `AgentReport` |
| **accounting** | The cash position and what is committed against it, vendor invoices and how overdue they are, margins on a proposed price, preparing payments for a human, and executing an approved one. | `get_cash_balance`, `list_invoices`, `list_vendors`, `check_discount_margin`, `request_payment_approval`, `record_payment`, `list_approvals`, `get_ticket` | `AgentReport` |
| **facilities** | The shop space — the Chapel Street lease, the landlord, rent, and checking a landlord's claim against the shop's own record. | `check_rent_due`, `get_cash_balance`, `request_payment_approval`, `record_payment`, `list_approvals`, `get_ticket` | `AgentReport` |
| **customer_service** | Drafting messages to the people who contacted the shop, accurately, including the bad news. Nothing is ever sent. | `get_ticket`, `check_stock`, `list_purchase_orders`, `draft_customer_message`, `list_message_drafts` | `AgentReport` |

Scoping is deliberate. Every agent connects to the same MCP server, but an agent that
can see a tool will eventually call it, so the allowlists are what keep customer
service out of the cash account and facilities out of stock orders.

### Full connectivity

Every agent carries a `delegate(to_agent, task)` tool listing the other four, so any
agent may hand work to any other — boss to inventory, inventory to accounting,
customer service to anyone. The structured report comes straight back to the caller.

Three guards keep that from running away, and all three are in code:

- **An agent is never its own peer**, so it cannot recurse into itself.
- **An agent already in the chain cannot be re-entered.** boss → inventory → boss is
  refused before it costs a token.
- **The chain is capped at two levels** (`MAX_DELEGATION_DEPTH`). At the limit, an
  agent is told to answer from its own tools or record the gap in `unknowns`.

A refused delegation returns a short explanation rather than raising, so the agent can
carry on with what it has; each refusal is written to the audit trail with its reason
(`not_a_peer`, `would_loop`, `depth_limit`).

### Structured output

Specialists return an `AgentReport` and the boss returns a `TicketDecision`, both in
`backend/models.py`. The shapes are doing real work: every `Finding` carries the
`source_tool` it came from, and both types have an `unknowns` list. An agent that has
to name its source for each fact and file what it could not establish has a harder time
rounding off an answer than one writing free prose.

### Observed behaviour

A live run on ticket 102 (rent): the boss read the ticket, delegated to facilities,
facilities verified $2,400 due 2026-09-02 against the shop's date, delegated onward to
accounting, which surfaced the $840 overdue invoice; the boss came back with the
$3,240-against-$3,400 squeeze and left the ticket `waiting_approval` with approval #1
queued. 20 requests, 27 tool calls, 54k tokens, four agents in the trail.

---

## 8. Every MCP tool and the table it reads

Eighteen tools. The three from Problem 3 are unchanged; fifteen were added here.

### Reading

| Tool | Tables | What it is for |
|---|---|---|
| `list_tickets` | `tickets` | The work queue, filtered by status. |
| `get_ticket` | `tickets` | One ticket, including the requester's own words. |
| `check_stock` | `inventory`, `desk` | Units on hand for a SKU and size, and the shortfall. |
| `check_rent_due` | `leases`, `desk` | Rent owed and days until due. |
| `check_discount_margin` | `pricing` | Cost, list, break-even, and the margin at a proposed price. |
| `list_vendors` | `vendors`, `invoices`, `desk` | Lead times and `will_ship`. |
| `list_invoices` | `invoices`, `vendors`, `desk` | Amounts and days overdue. |
| `get_cash_balance` | `cash_accounts`, `approvals`, `desk` | Balance, committed, and uncommitted. |
| `list_approvals` | `approvals` | What is waiting on a human. |
| `list_purchase_orders` | `purchase_orders` | Restocks ordered and their arrival dates. |
| `list_message_drafts` | `message_drafts` | Drafts already written. |

### Writing

| Tool | Tables written | |
|---|---|---|
| `update_ticket` | `tickets` | Status plus an appended note. |
| `request_payment_approval` | `approvals` | Queues a payment. Pays nothing. |
| `request_purchase_order_approval` | `approvals` | Queues an order. Orders nothing. |
| `record_payment` | `cash_accounts`, `payments`, `invoices` or `leases`, `approvals` | Executes an approved payment, in one transaction. |
| `place_purchase_order` | `purchase_orders`, `approvals` | Executes an approved order. Does not touch `inventory`. |
| `draft_customer_message` | `message_drafts` | Saves a draft to the board. |

### Human only

| Tool | Tables | |
|---|---|---|
| `decide_approval` | `approvals` | Approve or reject. Given to **no** agent. |

`approvals`, `purchase_orders`, and `message_drafts` do not exist in the original
schema. They are created on demand in the working copy and are cleared by a reset.

---

## 9. Safety

### Payments

- **No agent can approve anything.** `decide_approval` is on no role's allowlist, and
  `roles.assert_no_agent_can_approve()` raises at import if that ever changes. This is
  the mechanism; the sentences in the prompts are only a reminder of it.
- **Requesting is not paying.** `request_payment_approval` writes a row to `approvals`
  and touches no money. The test suite asserts cash and `payments` are untouched.
- **`record_payment` refuses** a request that is pending, rejected, already executed,
  or has no human in `decided_by`.
- **No negative balance, ever.** Cash is checked when the request is made *and*
  re-read inside the transaction at the moment of payment, because the two can be
  minutes apart. A payment that no longer fits is refused and the approval is left
  approved rather than consumed.
- **Queued money is treated as spent.** `get_cash_balance` reports `uncommitted`
  alongside `balance`, so two payments that each fit are not both approved into an
  overdraft.
- **The amount must match the debt.** Requesting $1,200 against $2,400 of rent is
  refused rather than part-paid.
- **No double payment.** A duplicate request for an invoice or lease that already has
  one queued is refused, and an executed approval cannot be executed twice.
- Every payment row records `approved_by` — the human's name, never an agent's.

### Vendors

- **A vendor holding an open invoice will not ship.** Enforced at both ends: a
  purchase order cannot be *requested* from a blocked vendor, and `place_purchase_order`
  re-checks the hold at execution in case an invoice opened in between.
- **Ordering is not receiving.** A purchase order records an expected date computed
  from `vendors.lead_days` and the shop's own date. It never increments `inventory` —
  the shelf changes when the goods arrive, which is after today.
- **No vendor is contacted.** There is no tool that reaches outside the shop.

### Customer data

- **Nothing is sent.** `draft_customer_message` writes to the board for a person to
  read and send. There is no email path, and customer service has no tool that could
  create one.
- **The trail does not collect personal data.** `backend/audit.py` redacts `email`,
  `phone`, and `address` keys at any nesting depth, alongside keys and tokens. What
  remains is the requester name already printed on the public ticket.
- **Drafts may not mention the shop's internals** — no balances, no vendor invoices,
  no approval queues, no agent names. That is in the customer service prompt and is
  the kind of leak a draft is most likely to contain.

### Honesty about facts

- Tools refuse rather than guess. An unstocked size errors with the sizes actually
  carried instead of returning `0`; "we do not carry it" and "we are out of it" are
  different answers to give a customer.
- Unknown SKUs, accounts, leases, and tickets are refused by name.
- Every `Finding` must name the tool it came from, and anything that could not be
  established goes in `unknowns` rather than into the summary.

### The database

- The original `data/campus_customs.db` is never opened for writing. The tests assert
  its hash is unchanged after every run.
- The database path is resolved inside `mcp_server/db.py` from the file's own
  location, so there is no configuration setting anyone can point at the original.
- All SQL is parameterised. No query is built by concatenating a tool argument.

---

## 10. Limits on tokens and runaway loops

Multi-agent chats get expensive quickly, and the expensive failure is not one agent
looping — it is five agents handing work around in a circle, each one cheap.

| Limit | Value | Why |
|---|---|---|
| `request_limit` | 24 | Model calls per ticket. |
| `tool_calls_limit` | 40 | Tool calls per ticket. |
| `total_tokens_limit` | 120,000 | Tokens per ticket. |
| `MAX_DELEGATION_DEPTH` | 2 | boss → specialist → specialist, then stop. |
| `OUTPUT_RETRIES` | 2 | Retries on malformed structured output, per agent. |
| `MAX_VALUE_CHARS` | 240 | Truncation in the audit trail, so it stays a log and not a second copy of the database. |

**The ceiling is per ticket, not per agent.** A delegated run is passed the caller's
`usage` object, so every agent the boss pulls in draws on the same budget. Without
that, a ticket could become arbitrarily expensive by spreading the cost across five
agents that each look reasonable alone.

When a limit is hit, `run_ticket` catches `UsageLimitExceeded`, returns a `RunRecord`
with `stop_reason="limit_exceeded"`, and writes that reason to the trail. The run
stops; it does not retry.

Proved rather than asserted: `scripts/test_agent_team.py` drives the team with a
`FunctionModel` that does nothing but delegate — the case a live model is least likely
to produce on demand. Self-delegation is refused, boss → inventory → boss is refused as
a loop, the depth cap fires, the run terminates on the request limit, and the stop
reason reaches the trail.

---

## 11. The audit trail

`output/audit_trail.json`, one JSON object per line, appended and never rewritten.

JSON Lines rather than one array for two reasons: a crashed run still leaves valid,
readable records instead of a truncated array no parser will touch, and appending a
line does not require rewriting everything before it.

| Event | Recorded when |
|---|---|
| `run_started` | A ticket run begins. Carries the model name and the limits in force. |
| `tool_call` | Every MCP tool call, via `process_tool_call` on the shared toolset — so it cannot be bypassed by an agent, and failures are recorded with the exception as well. |
| `delegation` | One agent hands work to another. |
| `delegation_returned` | The report comes back, with its duration. |
| `delegation_refused` | A delegation was blocked, with the reason. |
| `run_finished` | The run ends, with `stop_reason` and the usage totals. |

Each line carries the UTC time, the `run_id`, the acting agent, the ticket, the action,
the arguments, a summary of the result, the delegation depth, and the duration.

Not recorded: API keys and tokens, and `email`/`phone`/`address` at any depth. Long
values are clipped at 240 characters and long lists collapse to a count plus the first
two entries.

Append-only is tested rather than assumed: the suite counts the trail, writes a new
entry **from a separate process**, and asserts the count grew by exactly one and the
very first entry is byte-identical.

---

## 12. Tests

| Script | Covers | Result |
|---|---|---|
| `scripts/mcp_smoke.py` | The three original tools through the `.mcp.json` configuration, every value re-checked against independent SQL. | 3 tools, 23 field checks, 4 refusals — all pass |
| `scripts/test_shop_rules.py` | The shop rules, enforced against the real MCP server over stdio. | **35 pass, 0 fail** |
| `scripts/test_agent_team.py` | Team structure, the model lock, the loop guards, the limits, the trail, and one live run. | **47 pass, 0 fail** |

`test_shop_rules.py` covers: a payment cannot be made without approval; an approval
with no human named is refused; approval alone moves no money; an approved payment
debits cash and closes the invoice; the same approval cannot be paid twice; a blocked
vendor cannot be ordered from; the hold lifts once the invoice is paid; queued money is
treated as committed; a payment larger than the balance is refused at request time;
**an approved payment is still refused when the cash has gone, with the balance never
going negative and the approval left unconsumed**; wrong amounts, unknown accounts,
unknown tickets, and invalid statuses are refused; drafts stay on the board; and the
original database is untouched throughout.

`test_agent_team.py` runs offline with `--offline` for everything except the live run.

Both scripts reset the working copy before and after, so a test never leaves the shop
half-resolved.

---

## 13. Backend routes

`backend/main.py`, started from inside `backend/`:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Served at `http://localhost:8000`, with CORS open to the Vite dev server on ports
5173 and 5174 so the dashboard can call it. Interactive docs at `/docs`.

**No shop data is read or written in `main.py` directly.** Every figure comes back
through the MCP server — the same door the agents use — so the rules enforced in the
tools cannot be sidestepped by calling the API instead of an agent. The one exception
is `POST /api/reset`, which copies a file and is not a shop operation.

### The routes

| Method | URL | What it does |
|---|---|---|
| `GET` | `/api/tickets` | Every ticket on the board with `is_open` / `is_resolved`, the requester's own wording, and the sku/lease/invoice links that say which agent owns it. |
| `GET` | `/api/tickets/{ticket_id}` | One ticket in full. 404 if the board has no such ticket. |
| `POST` | `/api/tickets/{ticket_id}/run` | Sets the agent team to work on one ticket. Returns `202` with a run id immediately; the conversation runs in the background. 503 without an API key, 409 if a ticket is already being worked. |
| `GET` | `/api/runs/{run_id}` | The outcome of a run: the boss's decision, the agents consulted, usage, and why it stopped. |
| `GET` | `/api/runs` | Every run this server has started, for a history panel. |
| `GET` | `/api/events` | Recent agent activity — who acted, what they said, which MCP tool they called and what came back. Takes `since`, `limit`, and `run_id`. |
| `GET` | `/api/approvals` | Payments and orders the agents have queued, and what has been decided about each. |
| `POST` | `/api/approvals/{approval_id}/decide` | **The only route that moves money.** A person approves or rejects; on approval the payment is executed or the order placed, and their name is written to `payments.approved_by`. |
| `GET` | `/api/cash` | The checking balance from `cash_accounts`, plus what is already committed to queued approvals and what is genuinely free. |
| `GET` | `/api/drafts` | Customer messages the team has drafted. Nothing here has been sent. |
| `GET` | `/api/purchase-orders` | Restock orders placed, with the date each is expected to arrive. |
| `POST` | `/api/reset` | Restores `data/campus_customs_new.db` from the untouched original, for a fresh run. Keeps the audit trail. |
| `GET` | `/api/health` | Whether the pieces are wired up: the model, the key, the five agents, the MCP tool list, and the limits in force. |

### Three decisions behind that table

**Running a ticket is asynchronous.** A full agent conversation takes 20–40 seconds. A
synchronous `POST` would hold an HTTP request open that long and give the dashboard
nothing to show in the meantime. Instead the run starts in the background and the
dashboard polls `/api/events`, which is where the interesting part is anyway — the
delegations and tool calls as they happen. `RUN_LOCK` allows one run at a time;
two concurrent runs would race on the approval queue and could queue the same payment
twice.

**The run id the dashboard holds is the audit run id.** `run_ticket` accepts the
caller's id rather than minting its own, so `/api/events?run_id=…` filters on exactly
the run being watched. Two ids for one run would have left the dashboard unable to
filter the trail it was displaying — which is how the first version of this failed its
own test.

**`/api/events` reads the audit file rather than an in-memory copy.** The dashboard
sees the same record an auditor would read afterwards, not a second, prettier account
of events.

### Approval is where the two halves meet

An agent can call `request_payment_approval` and go no further. The row it writes
moves no money and the balance does not change — the test suite asserts that after a
full agent run the balance is still $3,400.00, with the queued amount showing only as
*committed*.

`POST /api/approvals/{id}/decide` is what a person clicking **Approve** triggers, and
it is the only path to a cash change. Approving is still not a guarantee: the payment
tool re-reads the balance at that moment and refuses with a `409` rather than
overdrawing, leaving the approval approved and nothing written. Tool refusals are
surfaced with the tool's own wording — "A human must approve a payment before it can
be made" is a better answer than a generic 500, and it is the shop's rule talking.

### Reset

`POST /api/reset` closes the MCP connection, copies the original database over the
working copy, and reopens. The approval queue, placed orders, and drafts live in the
working copy and are cleared with everything else.

**The audit trail is deliberately not reset.** It is a separate file and append-only
across resets. There is also no MCP tool for resetting, and there should not be:
nothing an agent can reach should be able to erase the record of what it did.

### Tested

`scripts/test_routes.py` drives every route against a running server — **41 checks,
0 failures**, including a live agent run on ticket 102. It verifies the balance is
untouched by the agents, that the human decision is what moves it ($3,400 → $1,000),
that the same approval cannot be approved twice, that an approval with no name is
rejected, and that a reset clears the queue while the trail survives.

```bash
.venv/bin/python scripts/test_routes.py            # everything
.venv/bin/python scripts/test_routes.py --offline  # skip the agent run
```

---

## 14. The dashboard

`frontend/` — React 19, Vite, TypeScript. Started from the frontend directory:

```bash
cd frontend
npm install
npm run dev
```

Served at `http://localhost:5173` and calling the backend at `http://localhost:8000`,
which lists the dev-server origins in its CORS middleware. `VITE_API_BASE` overrides
the backend host; see `frontend/.env.example`.

Three columns matching how the work moves — the board on the left, the work surface in
the middle, the money on the right. The full design rationale is in
[`output/design.md`](design.md); what follows is only the wiring.

| Requirement | Where it lives |
|---|---|
| List all three tickets | `App.tsx` left rail, from `GET /api/tickets` |
| Select a ticket and start its team | `selectTicket` + `POST /api/tickets/{id}/run` |
| Show each agent's messages and activity | `components/ActivityFeed.tsx`, polling `GET /api/events?run_id=` every 1.5s |
| Mark a ticket resolved | status chips from the backend, plus a **Mark resolved** control calling `POST /api/tickets/{id}/resolve` |
| Summarise what each agent did | `components/Decision.tsx`, built from the run's own trail |
| Approve a payment or purchase | `components/MoneyRail.tsx` → `POST /api/approvals/{id}/decide` |
| Show the checking balance, updated after a payment | the counter and the till panel, from `GET /api/cash` |

### One route added for the dashboard

`POST /api/tickets/{ticket_id}/resolve` closes a ticket off, through the MCP
`update_ticket` tool.

It exists because **the agents do not resolve tickets, and should not**. A run on
ticket 102 ends in `waiting_approval`, not `resolved`, because a correct plan is not a
finished job — the rent is still unpaid at that point. Closing the ticket is the
person's call, so it is a human route, and it is refused while anything on that ticket
is still queued for a decision: a ticket cannot be finished while the shop is waiting
on a signature.

### Verified in the browser

Driven end to end against the running backend, not just typechecked:

- Ticket 102 run from the dashboard: four agents in the feed, the approval appearing in
  the right rail, **Approve & pay** clicked, the counter going $3,400.00 → $1,000.00,
  and the executed approval moving to *Already decided* stamped with the approver's
  name.
- Ticket 103 run: the `blocked` chip on the board, 36 feed lines, the decision sheet,
  and the customer draft marked **Not sent**.
- Contrast measured on every rendered text node against its actual background:
  **0 failures**. The first pass found `--ink-3` at 4.10:1 on the sunk rail ground and
  it was darkened to `#5f6775` (4.75:1).
- Desktop (1440), tablet, and phone (375) layouts; no console warnings; `tsc -b` and
  `npm run build` both clean.

---

## 15. Resolving all three tickets

A full run, from a reset shop through to three resolved tickets. Driven from the
dashboard; every figure below is read back out of `output/audit_trail.json` and
`data/campus_customs_new.db` by `scripts/collect_run_evidence.py`.

### The cash

| | Amount | Balance |
|---|---|---|
| Opening, recorded after the reset | | **$3,400.00** |
| Ticket 101 — invoice 501, Bulldog Print Co | −$840.00 | $2,560.00 |
| Ticket 102 — rent, lease 1 | −$2,400.00 | $160.00 |
| Ticket 103 — purchase order **rejected** | $0.00 | $160.00 |
| **Closing** | **−$3,240.00** | **$160.00** |

`cash_accounts.balance` in the working copy reads **160.0**. The ledger and the
database agree exactly. Both payments name **Christina McBride** in
`payments.approved_by`; neither was made by an agent.

### What happened to each ticket

| | Agents | Hops | Human decisions | Runs | Outcome |
|---|---|---|---|---|---|
| **101** Bulldog tee | all four specialists | 11 | paid $840, ordered $8 | 3 | Invoice cleared, one tee on order for 2026-09-05, draft on the board. The customer does not have the tee yet, and the ticket says so. |
| **102** Rent due | boss, facilities, accounting, customer service | 10 | paid $2,400 | 3 | Rent paid, lease rolled to 2026-10-02. The only ticket that is completely finished. |
| **103** Bulk discount | boss, inventory, accounting, customer service | 5 (+1 refused) | rejected $264 | 1 | 8 of 20 in stock, margin established at $22 cost against $58 list, order declined as unaffordable, honest draft on the board. |

Seven runs, 119 model requests, 167 tool calls, 346,241 tokens. Every run stayed inside
the per-ticket ceiling.

### What the guardrails did under load

- **No agent moved money.** Across 167 tool calls, every cash change came from a person
  clicking Approve.
- **The vendor hold blocked a real request.** Ticket 101's first pass could not request
  a restock at all — `request_purchase_order_approval` refused while invoice 501 was
  open. The order only became possible after the payment cleared.
- **The loop guard fired in production.** On ticket 103, customer service tried to
  delegate back to the boss, already up-chain, and was stopped with `would_loop` before
  it reached the model. Until then it had only fired in tests.
- **No agent invented a fact.** Every draft is consistent with what the tools returned,
  including the unwelcome parts.

### Two failures, and the fix

Both repeat failures were the same failure: **an agent that analysed correctly and then
did not act.**

Facilities read the lease twice on ticket 102, confirmed $2,400 was owed and
affordable, wrote about it — and queued nothing, leaving the human to do the work the
agent had been asked to do. Inventory did the same with the restock on ticket 101.

In both cases the prompt already said to act. The durable fix was moving the
requirement out of the prompt and into code: an `@agent.output_validator` on the two
money agents rejects any report claiming a person needs to act while queueing nothing
and naming nothing blocking it, with a `ModelRetry` telling it to queue or explain.
That is the same lesson the payment rules taught earlier — **a rule that matters
belongs in the tool or the validator, not in the instructions.**

### The gap this run exposed

`record_payment` refuses to overdraw the account. `place_purchase_order` has no
equivalent check, because a purchase order moves no cash at the moment it is placed.
So the shop was free to commit to **$264 of goods against $160 of cash**, and nothing
in the tools would have stopped it.

The boss agent noticed unprompted — its rationale says the order "exceeds available
uncommitted cash" — and the order was rejected at the desk. But catching it depended on
a model's judgement and a human's click, not on a rule. Of everything in this system,
that is the gap I would close first.

### Where the evidence lives

| File | |
|---|---|
| `output/resolved_tickets.json` | Per ticket: final status, outcome, what each agent contributed, and every human approval. |
| `output/desk_tickets.html` | The plan written before the run, unedited, beside what actually happened. Cash tab carries the full ledger and the reconciliation. |
| `output/resolved_board.html` | The dashboard after each ticket was resolved, captured from the running app. |
| `output/audit_trail.json` | Every step of all seven runs, appended to what was already there. |
| `output/run_evidence.json` | The machine-readable source the two HTML pages were filled in from. |
