"""Campus Customs MCP server.

The shared tool surface for the agent team. Every agent — boss, inventory,
accounting, facilities, customer service — reaches the shop's data through
these tools and through no other route, so there is one place where the shop's
rules are enforced and one place to audit what the team actually looked at.

This problem adds the three read tools the three open tickets need. Tools that
move money or change stock come later; nothing here writes to the database.

Run it with:

    .venv/bin/python mcp_server/server.py
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

try:  # running as a package (from the backend)
    from .db import connect, today
except ImportError:  # running the file directly, as the MCP command does
    from db import connect, today

mcp = FastMCP(
    name="campus-customs-ops",
    instructions=(
        "Operations data for the Campus Customs shop on Chapel Street. "
        "Every figure these tools return is read straight from the shop "
        "database. If a tool reports that something is missing, it is missing "
        "— do not substitute an estimate."
    ),
)


def _parse_iso(value: str, field: str) -> date:
    """Turn a stored `YYYY-MM-DD` string into a date, or say which field is bad."""
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise ToolError(f"{field} is not a usable date: {value!r}") from exc


# ---------------------------------------------------------------------------
# Tool 1 — stock on hand. Ticket 101.
# ---------------------------------------------------------------------------


class StockCheck(BaseModel):
    """What the shelf actually holds for one SKU in one size."""

    sku: str
    product_name: str
    size: str
    quantity_on_hand: int
    location: str = Field(description="Aisle the stock sits in.")
    quantity_requested: int
    can_fill_from_stock: bool
    shortfall: int = Field(
        description="How many units are missing. 0 when the order can be filled."
    )
    as_of: str = Field(description="The shop's own date, from desk.date_today.")


@mcp.tool
def check_stock(sku: str, size: str, quantity_requested: int = 1) -> StockCheck:
    """Report units on hand for one SKU and size, and whether an order can be filled.

    Use this before promising anything to a customer. It answers the only
    question that matters first: is the item on the shelf right now, and if
    not, how many are missing?

    Sizes are stored as S, M, L, XL, or OS for one-size goods. A SKU and size
    that are not in the inventory table are reported as an error rather than as
    zero stock — those are different facts.
    """
    if quantity_requested < 1:
        raise ToolError("quantity_requested must be at least 1.")

    with connect() as conn:
        row = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory "
            "WHERE sku = ? AND size = ?",
            (sku.strip().upper(), size.strip().upper()),
        ).fetchone()

        if row is None:
            known = conn.execute(
                "SELECT size FROM inventory WHERE sku = ? ORDER BY size",
                (sku.strip().upper(),),
            ).fetchall()
            if known:
                sizes = ", ".join(r["size"] for r in known)
                raise ToolError(
                    f"{sku} is not stocked in size {size}. Sizes carried: {sizes}."
                )
            raise ToolError(f"There is no SKU {sku!r} in the inventory table.")

        on_hand = int(row["qty"])
        shortfall = max(0, quantity_requested - on_hand)
        return StockCheck(
            sku=row["sku"],
            product_name=row["name"],
            size=row["size"],
            quantity_on_hand=on_hand,
            location=row["location"],
            quantity_requested=quantity_requested,
            can_fill_from_stock=shortfall == 0,
            shortfall=shortfall,
            as_of=today(conn),
        )


# ---------------------------------------------------------------------------
# Tool 2 — rent obligations. Ticket 102.
# ---------------------------------------------------------------------------


class RentObligation(BaseModel):
    """One lease, and where its next rent payment sits against the shop's date."""

    lease_id: int
    space_name: str
    landlord: str
    monthly_rent: float
    next_due: str
    as_of: str = Field(description="The shop's own date, from desk.date_today.")
    days_until_due: int = Field(
        description="Negative when the payment is already late."
    )
    is_overdue: bool
    notes: str | None = None


@mcp.tool
def check_rent_due(lease_id: int | None = None) -> list[RentObligation]:
    """List lease rent obligations with how many days remain until each is due.

    Timing is measured against `desk.date_today`, the shop's own calendar, not
    against the real-world date. Pass a `lease_id` for one space, or leave it
    out to see every lease the shop holds.

    This reports what is owed. It does not pay anything — rent leaves the
    account only through the payment tool, and only after a human approves it.
    """
    with connect() as conn:
        if lease_id is None:
            rows = conn.execute("SELECT * FROM leases ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM leases WHERE id = ?", (lease_id,)
            ).fetchall()
            if not rows:
                raise ToolError(f"There is no lease with id {lease_id}.")
        as_of = today(conn)

    shop_date = _parse_iso(as_of, "desk.date_today")
    obligations = []
    for row in rows:
        due = _parse_iso(row["next_due"], f"leases.next_due for lease {row['id']}")
        delta = (due - shop_date).days
        obligations.append(
            RentObligation(
                lease_id=int(row["id"]),
                space_name=row["space_name"],
                landlord=row["landlord"],
                monthly_rent=float(row["monthly_rent"]),
                next_due=row["next_due"],
                as_of=as_of,
                days_until_due=delta,
                is_overdue=delta < 0,
                notes=row["notes"] or None,
            )
        )
    return obligations


# ---------------------------------------------------------------------------
# Tool 3 — margin on a discount request. Ticket 103.
# ---------------------------------------------------------------------------


class DiscountQuote(BaseModel):
    """Cost, list price, and what a proposed discount would do to the margin."""

    sku: str
    quantity: int
    unit_cost: float
    list_price: float
    list_total: float
    list_margin_per_unit: float
    list_margin_percent: float = Field(description="Margin as a percent of price.")
    proposed_unit_price: float | None = None
    proposed_total: float | None = None
    proposed_margin_per_unit: float | None = None
    proposed_margin_percent: float | None = None
    discount_percent_off_list: float | None = None
    covers_unit_cost: bool | None = Field(
        default=None,
        description="False when the proposed price sells below what the shop paid.",
    )
    break_even_unit_price: float = Field(
        description="The unit cost. Any price at or below this earns the shop nothing."
    )


@mcp.tool
def check_discount_margin(
    sku: str,
    quantity: int,
    proposed_unit_price: float | None = None,
) -> DiscountQuote:
    """Price a bulk request and show the margin at list and at a proposed discount.

    Use this to answer a discount ask with numbers instead of a guess. Costs
    and list prices come from the pricing table; nothing is estimated. Leave
    `proposed_unit_price` out to see the list-price position and the
    break-even floor before naming a figure.

    The tool reports the margin. It does not approve the discount.
    """
    if quantity < 1:
        raise ToolError("quantity must be at least 1.")
    if proposed_unit_price is not None and proposed_unit_price < 0:
        raise ToolError("proposed_unit_price cannot be negative.")

    with connect() as conn:
        row = conn.execute(
            "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?",
            (sku.strip().upper(),),
        ).fetchone()
        if row is None:
            raise ToolError(f"There is no pricing row for SKU {sku!r}.")

    unit_cost = float(row["unit_cost"])
    list_price = float(row["list_price"])
    quote = DiscountQuote(
        sku=row["sku"],
        quantity=quantity,
        unit_cost=unit_cost,
        list_price=list_price,
        list_total=round(list_price * quantity, 2),
        list_margin_per_unit=round(list_price - unit_cost, 2),
        list_margin_percent=round((list_price - unit_cost) / list_price * 100, 2)
        if list_price
        else 0.0,
        break_even_unit_price=unit_cost,
    )

    if proposed_unit_price is not None:
        margin = proposed_unit_price - unit_cost
        quote.proposed_unit_price = proposed_unit_price
        quote.proposed_total = round(proposed_unit_price * quantity, 2)
        quote.proposed_margin_per_unit = round(margin, 2)
        quote.proposed_margin_percent = (
            round(margin / proposed_unit_price * 100, 2) if proposed_unit_price else 0.0
        )
        quote.discount_percent_off_list = (
            round((list_price - proposed_unit_price) / list_price * 100, 2)
            if list_price
            else 0.0
        )
        quote.covers_unit_cost = proposed_unit_price >= unit_cost

    return quote


# ===========================================================================
# The board — what the shop has been asked to do.
# ===========================================================================


class TicketSummary(BaseModel):
    """One row of the board."""

    id: int
    type: str
    requester: str
    subject: str
    status: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    notes: str | None = None
    created_at: str


@mcp.tool
def list_tickets(status: str | None = "open") -> list[TicketSummary]:
    """List tickets on the board, newest first, optionally filtered by status.

    This is the work queue. Pass `status="open"` for what still needs doing,
    or `status=None` for everything including closed tickets.

    Which of `sku`, `lease_id`, and `invoice_id` are filled is the routing
    signal: a ticket carrying a SKU is a product question, one carrying a
    lease id belongs to facilities, one carrying an invoice id touches money.
    """
    with connect() as conn:
        if status is None:
            rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY id",
                (status.strip().lower(),),
            ).fetchall()
    return [TicketSummary(**dict(r)) for r in rows]


@mcp.tool
def get_ticket(ticket_id: int) -> TicketSummary:
    """Read one ticket in full, including the requester's own words in `notes`."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise ToolError(f"There is no ticket {ticket_id} on the board.")
    return TicketSummary(**dict(row))


class TicketUpdate(BaseModel):
    ticket_id: int
    status: str
    notes: str | None = None
    updated_on: str


TICKET_STATUSES = {"open", "in_progress", "waiting_approval", "blocked", "resolved"}


@mcp.tool
def update_ticket(
    ticket_id: int,
    status: str,
    note: str,
    updated_by: str,
) -> TicketUpdate:
    """Move a ticket to a new status and append a note saying why.

    Allowed statuses: open, in_progress, waiting_approval, blocked, resolved.

    Only mark a ticket `resolved` when the work is actually finished — a
    payment executed, an order placed, a message drafted on the board. A
    ticket waiting on a human decision is `waiting_approval`, not resolved.
    Notes are appended, never overwritten, so the history survives.
    """
    state = status.strip().lower()
    if state not in TICKET_STATUSES:
        raise ToolError(
            f"{status!r} is not a ticket status. Use one of: "
            + ", ".join(sorted(TICKET_STATUSES))
        )
    if not note.strip():
        raise ToolError("A note is required so the board records why this changed.")

    with connect() as conn:
        row = conn.execute(
            "SELECT notes FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if row is None:
            raise ToolError(f"There is no ticket {ticket_id} on the board.")
        stamp = today(conn)
        existing = (row["notes"] or "").rstrip()
        appended = f"{existing}\n[{stamp} {updated_by}] {note.strip()}".strip()
        conn.execute(
            "UPDATE tickets SET status = ?, notes = ? WHERE id = ?",
            (state, appended, ticket_id),
        )
        conn.commit()
    return TicketUpdate(
        ticket_id=ticket_id, status=state, notes=appended, updated_on=stamp
    )


# ===========================================================================
# Vendors and invoices — who can ship, and who the shop owes.
# ===========================================================================


class VendorStatus(BaseModel):
    """A vendor, plus whether an unpaid invoice is blocking them."""

    id: int
    name: str
    specialty: str
    lead_days: int
    open_invoice_ids: list[int]
    open_invoice_total: float
    will_ship: bool = Field(
        description="False when the vendor is holding an open, unpaid invoice."
    )
    earliest_arrival_if_ordered_today: str = Field(
        description="Shop date plus lead_days. Only meaningful when will_ship is true."
    )
    as_of: str


@mcp.tool
def list_vendors(vendor_id: int | None = None) -> list[VendorStatus]:
    """List vendors with lead times and whether an unpaid invoice is blocking them.

    Shop rule: a vendor will not ship new product while they still have an
    open, unpaid invoice. `will_ship` applies that rule, so check it before
    promising a restock date. When it is false, the invoices in
    `open_invoice_ids` have to be cleared first.

    `specialty` is the vendor's own free-text description. Read it and decide;
    do not expect it to match a SKU automatically.
    """
    with connect() as conn:
        if vendor_id is None:
            vendors = conn.execute("SELECT * FROM vendors ORDER BY id").fetchall()
        else:
            vendors = conn.execute(
                "SELECT * FROM vendors WHERE id = ?", (vendor_id,)
            ).fetchall()
            if not vendors:
                raise ToolError(f"There is no vendor with id {vendor_id}.")
        open_rows = conn.execute(
            "SELECT id, vendor_id, amount FROM invoices WHERE status = 'open'"
        ).fetchall()
        stamp = today(conn)

    shop_date = _parse_iso(stamp, "desk.date_today")
    out = []
    for v in vendors:
        mine = [r for r in open_rows if r["vendor_id"] == v["id"]]
        out.append(
            VendorStatus(
                id=int(v["id"]),
                name=v["name"],
                specialty=v["specialty"],
                lead_days=int(v["lead_days"]),
                open_invoice_ids=[int(r["id"]) for r in mine],
                open_invoice_total=round(sum(float(r["amount"]) for r in mine), 2),
                will_ship=not mine,
                earliest_arrival_if_ordered_today=(
                    shop_date + timedelta(days=int(v["lead_days"]))
                ).isoformat(),
                as_of=stamp,
            )
        )
    return out


class InvoiceStatus(BaseModel):
    """One vendor bill and how late it is against the shop's date."""

    id: int
    vendor_id: int
    vendor_name: str
    amount: float
    due_date: str
    status: str
    description: str | None = None
    as_of: str
    days_overdue: int = Field(
        description="Positive when late, negative when it is not due yet."
    )
    is_overdue: bool


@mcp.tool
def list_invoices(status: str | None = "open") -> list[InvoiceStatus]:
    """List vendor invoices with how overdue each one is.

    Lateness is measured against `desk.date_today`, the shop's own calendar.
    Pass `status=None` to include invoices that have already been paid.

    An open invoice is both a bill and a blocker: it stops the vendor who
    issued it from shipping anything new.
    """
    with connect() as conn:
        sql = (
            "SELECT i.*, v.name AS vendor_name FROM invoices i "
            "JOIN vendors v ON v.id = i.vendor_id"
        )
        if status is None:
            rows = conn.execute(sql + " ORDER BY i.due_date").fetchall()
        else:
            rows = conn.execute(
                sql + " WHERE i.status = ? ORDER BY i.due_date",
                (status.strip().lower(),),
            ).fetchall()
        stamp = today(conn)

    shop_date = _parse_iso(stamp, "desk.date_today")
    out = []
    for r in rows:
        due = _parse_iso(r["due_date"], f"invoices.due_date for invoice {r['id']}")
        late = (shop_date - due).days
        out.append(
            InvoiceStatus(
                id=int(r["id"]),
                vendor_id=int(r["vendor_id"]),
                vendor_name=r["vendor_name"],
                amount=float(r["amount"]),
                due_date=r["due_date"],
                status=r["status"],
                description=r["description"],
                as_of=stamp,
                days_overdue=late,
                is_overdue=late > 0 and r["status"] == "open",
            )
        )
    return out


# ===========================================================================
# Cash.
# ===========================================================================


class CashBalance(BaseModel):
    account: str
    balance: float
    as_of: str
    committed_to_pending_approvals: float = Field(
        description="Total of payments already queued for human approval."
    )
    uncommitted: float = Field(
        description="Balance minus what is already queued. What is really free."
    )


@mcp.tool
def get_cash_balance(account: str = "checking") -> CashBalance:
    """Read a cash account balance, and how much of it is already spoken for.

    No revenue is modelled in this shop, so this number only ever falls. Check
    `uncommitted` rather than `balance` before proposing a new payment —
    `balance` ignores the payments already sitting in the approval queue, and
    two separately affordable payments can be unaffordable together.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT name, balance, date FROM cash_accounts WHERE name = ?",
            (account.strip().lower(),),
        ).fetchone()
        if row is None:
            known = conn.execute("SELECT name FROM cash_accounts").fetchall()
            raise ToolError(
                f"There is no cash account named {account!r}. "
                f"Accounts: {', '.join(r['name'] for r in known)}."
            )
        pending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM approvals "
            "WHERE kind = 'payment' AND status IN ('pending', 'approved') "
            "AND account = ?",
            (row["name"],),
        ).fetchone()["total"]
        stamp = today(conn)

    balance = float(row["balance"])
    return CashBalance(
        account=row["name"],
        balance=balance,
        as_of=stamp,
        committed_to_pending_approvals=round(float(pending), 2),
        uncommitted=round(balance - float(pending), 2),
    )


# ===========================================================================
# The approval queue.
#
# No money moves and no order is placed without a human decision. Agents can
# only ever *request*; `decide_approval` is the human's tool and is kept out
# of every agent's toolset.
# ===========================================================================


class ApprovalRecord(BaseModel):
    id: int
    kind: str
    ticket_id: int | None = None
    requested_by: str
    summary: str
    amount: float
    account: str | None = None
    payload: dict
    status: str
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None
    executed_at: str | None = None


def _approval_row_to_model(row) -> ApprovalRecord:
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    return ApprovalRecord(**data)


@mcp.tool
def list_approvals(status: str | None = None) -> list[ApprovalRecord]:
    """List approval requests and where each one stands.

    Statuses run pending -> approved or rejected -> executed. Use this to
    check whether something you already asked for has been decided, instead
    of asking for it a second time.
    """
    with connect() as conn:
        if status is None:
            rows = conn.execute("SELECT * FROM approvals ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY id",
                (status.strip().lower(),),
            ).fetchall()
    return [_approval_row_to_model(r) for r in rows]


PAYMENT_KINDS = {"invoice", "rent"}


@mcp.tool
def request_payment_approval(
    ticket_id: int,
    pays_for: str,
    ref_id: int,
    amount: float,
    reason: str,
    requested_by: str,
    account: str = "checking",
) -> ApprovalRecord:
    """Queue a payment for a human to approve. This does NOT pay anything.

    `pays_for` is "invoice" or "rent"; `ref_id` is the invoice id or the lease
    id it settles. The amount must match what the shop actually owes — do not
    round it or make one up.

    The request is refused outright if the account cannot cover it once the
    payments already queued are counted. No revenue comes into this shop, so a
    payment that does not fit today will not fit later either, and queueing it
    would only invite a human to approve something impossible.

    Money moves later, through `record_payment`, and only after a human has
    approved this request.
    """
    kind = pays_for.strip().lower()
    if kind not in PAYMENT_KINDS:
        raise ToolError(
            f"pays_for must be one of {sorted(PAYMENT_KINDS)}, not {pays_for!r}."
        )
    if amount <= 0:
        raise ToolError("A payment amount must be positive.")
    if not reason.strip():
        raise ToolError("A reason is required; a human has to decide from it.")

    with connect() as conn:
        stamp = today(conn)
        acct = conn.execute(
            "SELECT name, balance FROM cash_accounts WHERE name = ?",
            (account.strip().lower(),),
        ).fetchone()
        if acct is None:
            raise ToolError(f"There is no cash account named {account!r}.")

        # Confirm the thing being paid for exists and matches the amount.
        if kind == "invoice":
            target = conn.execute(
                "SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)
            ).fetchone()
            if target is None:
                raise ToolError(f"There is no invoice {ref_id}.")
            if target["status"] != "open":
                raise ToolError(
                    f"Invoice {ref_id} is already {target['status']}; nothing to pay."
                )
            owed = float(target["amount"])
        else:
            target = conn.execute(
                "SELECT monthly_rent FROM leases WHERE id = ?", (ref_id,)
            ).fetchone()
            if target is None:
                raise ToolError(f"There is no lease {ref_id}.")
            owed = float(target["monthly_rent"])

        if abs(owed - amount) > 0.005:
            raise ToolError(
                f"The shop owes {owed:.2f} on that {kind}, not {amount:.2f}. "
                "Request the amount actually owed."
            )

        pending = float(
            conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS t FROM approvals "
                "WHERE kind = 'payment' AND status IN ('pending', 'approved') "
                "AND account = ?",
                (acct["name"],),
            ).fetchone()["t"]
        )
        free = float(acct["balance"]) - pending
        if amount > free + 0.005:
            raise ToolError(
                f"Refused: {acct['name']} holds {float(acct['balance']):.2f} with "
                f"{pending:.2f} already queued for approval, leaving {free:.2f}. "
                f"A payment of {amount:.2f} would overdraw the account, and this "
                "shop has no incoming revenue to cover it."
            )

        duplicate = conn.execute(
            "SELECT id FROM approvals WHERE kind = 'payment' AND status IN "
            "('pending', 'approved') AND json_extract(payload, '$.pays_for') = ? "
            "AND json_extract(payload, '$.ref_id') = ?",
            (kind, ref_id),
        ).fetchone()
        if duplicate:
            raise ToolError(
                f"Approval {duplicate['id']} is already queued for that {kind}. "
                "Check list_approvals before requesting again."
            )

        payload = {"pays_for": kind, "ref_id": ref_id, "reason": reason.strip()}
        summary = (
            f"Pay {amount:.2f} from {acct['name']} for "
            f"{kind} {ref_id} — {reason.strip()}"
        )
        cur = conn.execute(
            "INSERT INTO approvals (kind, ticket_id, requested_by, summary, amount, "
            "account, payload, status, created_at) "
            "VALUES ('payment', ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                ticket_id,
                requested_by,
                summary,
                round(amount, 2),
                acct["name"],
                json.dumps(payload),
                stamp,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _approval_row_to_model(row)


@mcp.tool
def request_purchase_order_approval(
    ticket_id: int,
    vendor_id: int,
    sku: str,
    size: str,
    quantity: int,
    reason: str,
    requested_by: str,
) -> ApprovalRecord:
    """Queue a restock order for a human to approve. This does NOT order anything.

    The unit cost comes from the pricing table, so the total is the shop's own
    figure and not an estimate. The request is refused if the vendor is
    currently blocked by an open invoice, because they would not ship it.

    Goods are ordered later, through `place_purchase_order`, and only after a
    human has approved this request.
    """
    if quantity < 1:
        raise ToolError("quantity must be at least 1.")
    if not reason.strip():
        raise ToolError("A reason is required; a human has to decide from it.")

    sku = sku.strip().upper()
    size = size.strip().upper()

    with connect() as conn:
        stamp = today(conn)
        vendor = conn.execute(
            "SELECT * FROM vendors WHERE id = ?", (vendor_id,)
        ).fetchone()
        if vendor is None:
            raise ToolError(f"There is no vendor with id {vendor_id}.")

        price = conn.execute(
            "SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()
        if price is None:
            raise ToolError(f"There is no pricing row for SKU {sku!r}.")

        stocked = conn.execute(
            "SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)
        ).fetchone()
        if stocked is None:
            raise ToolError(f"The shop does not carry {sku} in size {size}.")

        blocking = conn.execute(
            "SELECT id, amount FROM invoices WHERE vendor_id = ? AND status = 'open'",
            (vendor_id,),
        ).fetchall()
        if blocking:
            ids = ", ".join(str(r["id"]) for r in blocking)
            total = sum(float(r["amount"]) for r in blocking)
            raise ToolError(
                f"Refused: {vendor['name']} will not ship while invoice(s) {ids} "
                f"are open ({total:.2f} outstanding). Clear the invoice first, "
                "then request the order."
            )

        unit_cost = float(price["unit_cost"])
        total_cost = round(unit_cost * quantity, 2)
        expected = (
            _parse_iso(stamp, "desk.date_today")
            + timedelta(days=int(vendor["lead_days"]))
        ).isoformat()
        payload = {
            "vendor_id": vendor_id,
            "vendor_name": vendor["name"],
            "sku": sku,
            "size": size,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "total_cost": total_cost,
            "expected_on": expected,
            "reason": reason.strip(),
        }
        summary = (
            f"Order {quantity} x {sku} ({size}) from {vendor['name']} at "
            f"{unit_cost:.2f} each = {total_cost:.2f}, arriving {expected} — "
            f"{reason.strip()}"
        )
        cur = conn.execute(
            "INSERT INTO approvals (kind, ticket_id, requested_by, summary, amount, "
            "account, payload, status, created_at) "
            "VALUES ('purchase_order', ?, ?, ?, ?, NULL, ?, 'pending', ?)",
            (ticket_id, requested_by, summary, total_cost, json.dumps(payload), stamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _approval_row_to_model(row)


@mcp.tool(
    tags={"human-only"},
    annotations={"title": "Human decision on an approval request"},
)
def decide_approval(
    approval_id: int,
    decision: str,
    decided_by: str,
    note: str = "",
) -> ApprovalRecord:
    """HUMAN ONLY. Approve or reject a queued request.

    This tool is not given to any agent. It is called by the dashboard on
    behalf of the person sitting at the desk, and `decided_by` records that
    person's name. An agent that finds a way to call this has broken the one
    rule the shop cannot bend.

    `decision` is "approve" or "reject".
    """
    verdict = decision.strip().lower()
    if verdict not in {"approve", "reject"}:
        raise ToolError('decision must be "approve" or "reject".')
    if not decided_by.strip():
        raise ToolError("decided_by must name the person making this decision.")

    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            raise ToolError(f"There is no approval request {approval_id}.")
        if row["status"] != "pending":
            raise ToolError(
                f"Approval {approval_id} is already {row['status']}; it cannot be "
                "decided again."
            )
        stamp = today(conn)
        conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, "
            "decision_note = ? WHERE id = ?",
            (
                "approved" if verdict == "approve" else "rejected",
                stamp,
                decided_by.strip(),
                note.strip() or None,
                approval_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
    return _approval_row_to_model(row)


# ===========================================================================
# Carrying out an approved decision.
# ===========================================================================


def _add_one_month(iso: str) -> str:
    """Next month, same day of month, clamped to the end of a short month."""
    d = date.fromisoformat(iso)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in range(d.day, 27, -1):
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return date(year, month, d.day).isoformat()


class PaymentReceipt(BaseModel):
    payment_id: int
    approval_id: int
    pays_for: str
    ref_id: int
    amount: float
    account: str
    paid_on: str
    approved_by: str
    balance_before: float
    balance_after: float
    invoice_now: str | None = None
    lease_next_due_now: str | None = None


@mcp.tool
def record_payment(approval_id: int, executed_by: str) -> PaymentReceipt:
    """Carry out a payment that a human has already approved.

    Refuses unless the approval exists, is for a payment, and has status
    `approved` with a human recorded in `decided_by`. Refuses again if the
    balance will not cover it — the cash is re-read at this moment, not
    trusted from when the request was made. A negative balance is never
    written.

    On success it debits the account, writes a row to `payments` naming the
    human who approved it, and closes out what was paid: an invoice becomes
    `paid`, a lease rolls to next month's due date. All in one transaction, so
    a failure part-way leaves nothing behind.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            raise ToolError(f"There is no approval request {approval_id}.")
        if row["kind"] != "payment":
            raise ToolError(
                f"Approval {approval_id} is a {row['kind']} request, not a payment."
            )
        if row["status"] == "executed":
            raise ToolError(f"Approval {approval_id} has already been paid.")
        if row["status"] != "approved":
            raise ToolError(
                f"Refused: approval {approval_id} is {row['status']}. A human must "
                "approve a payment before it can be made."
            )
        if not (row["decided_by"] or "").strip():
            raise ToolError(
                f"Refused: approval {approval_id} has no human recorded in "
                "decided_by. Payments are never made on an agent's own authority."
            )

        payload = json.loads(row["payload"])
        kind, ref_id = payload["pays_for"], int(payload["ref_id"])
        amount = float(row["amount"])
        account = row["account"]
        stamp = today(conn)

        try:
            conn.execute("BEGIN IMMEDIATE")
            acct = conn.execute(
                "SELECT balance FROM cash_accounts WHERE name = ?", (account,)
            ).fetchone()
            if acct is None:
                raise ToolError(f"There is no cash account named {account!r}.")
            before = float(acct["balance"])
            if amount > before + 0.005:
                raise ToolError(
                    f"Refused: {account} holds {before:.2f} and the payment is "
                    f"{amount:.2f}. The shop does not allow a negative balance, "
                    "and no revenue is coming in to cover it."
                )

            after = round(before - amount, 2)
            conn.execute(
                "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
                (after, stamp, account),
            )
            cur = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, "
                "approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                (kind, ref_id, round(amount, 2), account, stamp, row["decided_by"]),
            )
            payment_id = int(cur.lastrowid)

            invoice_now = lease_now = None
            if kind == "invoice":
                conn.execute(
                    "UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,)
                )
                invoice_now = "paid"
            else:
                lease = conn.execute(
                    "SELECT next_due FROM leases WHERE id = ?", (ref_id,)
                ).fetchone()
                lease_now = _add_one_month(lease["next_due"])
                conn.execute(
                    "UPDATE leases SET next_due = ? WHERE id = ?", (lease_now, ref_id)
                )

            conn.execute(
                "UPDATE approvals SET status = 'executed', executed_at = ? WHERE id = ?",
                (stamp, approval_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return PaymentReceipt(
        payment_id=payment_id,
        approval_id=approval_id,
        pays_for=kind,
        ref_id=ref_id,
        amount=round(amount, 2),
        account=account,
        paid_on=stamp,
        approved_by=row["decided_by"],
        balance_before=before,
        balance_after=after,
        invoice_now=invoice_now,
        lease_next_due_now=lease_now,
    )


class PurchaseOrderReceipt(BaseModel):
    purchase_order_id: int
    approval_id: int
    vendor_id: int
    vendor_name: str
    sku: str
    size: str
    quantity: int
    unit_cost: float
    total_cost: float
    ordered_on: str
    expected_on: str
    approved_by: str
    note: str


@mcp.tool
def place_purchase_order(approval_id: int, executed_by: str) -> PurchaseOrderReceipt:
    """Place a restock order that a human has already approved.

    Refuses unless the approval is a purchase order with status `approved`
    and a human in `decided_by`. Re-checks the vendor hold at this moment:
    if an invoice has gone open since the request, the vendor still will not
    ship and the order is refused.

    No cash moves here. The goods are ordered, the arrival date is recorded
    as the shop's date plus the vendor's lead time, and stock is not
    incremented — the shelf changes when the delivery actually arrives, which
    is after today.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            raise ToolError(f"There is no approval request {approval_id}.")
        if row["kind"] != "purchase_order":
            raise ToolError(
                f"Approval {approval_id} is a {row['kind']} request, not an order."
            )
        if row["status"] == "executed":
            raise ToolError(f"Approval {approval_id} has already been ordered.")
        if row["status"] != "approved":
            raise ToolError(
                f"Refused: approval {approval_id} is {row['status']}. A human must "
                "approve an order before it is placed."
            )
        if not (row["decided_by"] or "").strip():
            raise ToolError(
                f"Refused: approval {approval_id} has no human recorded in "
                "decided_by."
            )

        payload = json.loads(row["payload"])
        vendor_id = int(payload["vendor_id"])
        stamp = today(conn)

        blocking = conn.execute(
            "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'",
            (vendor_id,),
        ).fetchall()
        if blocking:
            ids = ", ".join(str(r["id"]) for r in blocking)
            raise ToolError(
                f"Refused: {payload['vendor_name']} still has invoice(s) {ids} open "
                "and will not ship. Clear them before placing this order."
            )

        expected = (
            _parse_iso(stamp, "desk.date_today")
            + timedelta(
                days=int(
                    conn.execute(
                        "SELECT lead_days FROM vendors WHERE id = ?", (vendor_id,)
                    ).fetchone()["lead_days"]
                )
            )
        ).isoformat()

        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO purchase_orders (approval_id, vendor_id, sku, size, "
                "quantity, unit_cost, total_cost, ordered_on, expected_on, "
                "ticket_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'placed')",
                (
                    approval_id,
                    vendor_id,
                    payload["sku"],
                    payload["size"],
                    int(payload["quantity"]),
                    float(payload["unit_cost"]),
                    float(payload["total_cost"]),
                    stamp,
                    expected,
                    row["ticket_id"],
                ),
            )
            po_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE approvals SET status = 'executed', executed_at = ? WHERE id = ?",
                (stamp, approval_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return PurchaseOrderReceipt(
        purchase_order_id=po_id,
        approval_id=approval_id,
        vendor_id=vendor_id,
        vendor_name=payload["vendor_name"],
        sku=payload["sku"],
        size=payload["size"],
        quantity=int(payload["quantity"]),
        unit_cost=float(payload["unit_cost"]),
        total_cost=float(payload["total_cost"]),
        ordered_on=stamp,
        expected_on=expected,
        approved_by=row["decided_by"],
        note=(
            "Ordered, not received. Inventory is unchanged until the delivery "
            f"arrives on {expected}."
        ),
    )


# ===========================================================================
# Customer messages — drafted, never sent.
# ===========================================================================


class MessageDraft(BaseModel):
    id: int
    ticket_id: int
    drafted_by: str
    recipient: str
    subject: str
    body: str
    created_at: str
    status: str
    note: str = "Held on the board. This shop never sends mail from an agent."


@mcp.tool
def draft_customer_message(
    ticket_id: int,
    recipient: str,
    subject: str,
    body: str,
    drafted_by: str,
) -> MessageDraft:
    """Save a message to the customer on the board. Nothing is ever sent.

    There is no email in this shop and no way for an agent to contact anyone.
    The draft sits against the ticket for a person to read, edit, and send
    themselves.

    Write only what the tools have established. If a restock date is not
    confirmed, do not promise one; say what is known and what is not. A draft
    that guesses is worse than a draft that admits the gap, because a person
    may send it as written.
    """
    if not subject.strip() or not body.strip():
        raise ToolError("A draft needs both a subject and a body.")

    with connect() as conn:
        if conn.execute(
            "SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone() is None:
            raise ToolError(f"There is no ticket {ticket_id} to draft against.")
        stamp = today(conn)
        cur = conn.execute(
            "INSERT INTO message_drafts (ticket_id, drafted_by, recipient, subject, "
            "body, created_at, status) VALUES (?, ?, ?, ?, ?, ?, 'on_board')",
            (ticket_id, drafted_by, recipient, subject.strip(), body.strip(), stamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM message_drafts WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return MessageDraft(**dict(row))


@mcp.tool
def list_message_drafts(ticket_id: int | None = None) -> list[MessageDraft]:
    """Read the customer messages drafted so far, optionally for one ticket."""
    with connect() as conn:
        if ticket_id is None:
            rows = conn.execute("SELECT * FROM message_drafts ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM message_drafts WHERE ticket_id = ? ORDER BY id",
                (ticket_id,),
            ).fetchall()
    return [MessageDraft(**dict(r)) for r in rows]


@mcp.tool
def list_purchase_orders(ticket_id: int | None = None) -> list[dict]:
    """Read restock orders already placed, with their expected arrival dates."""
    with connect() as conn:
        if ticket_id is None:
            rows = conn.execute("SELECT * FROM purchase_orders ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM purchase_orders WHERE ticket_id = ? ORDER BY id",
                (ticket_id,),
            ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    # stdio is the transport Claude Code uses. The startup banner is
    # suppressed so nothing but protocol traffic goes near the pipe.
    mcp.run(transport="stdio", show_banner=False)
