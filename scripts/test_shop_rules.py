"""Prove the shop rules are enforced in tool code, not just written in prompts.

Every one of these runs against the real MCP server over stdio. The working
copy is reset to the original before the run and reset again afterwards, so
the test never leaves the shop in a half-resolved state.

    .venv/bin/python scripts/test_shop_rules.py
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "data" / "campus_customs.db"
WORKING = ROOT / "data" / "campus_customs_new.db"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))


def reset() -> None:
    shutil.copyfile(ORIGINAL, WORKING)


def write_sql(query: str, params: tuple = ()) -> None:
    """Direct write, used only to set up a test. No tool may do this."""
    conn = sqlite3.connect(WORKING)
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def sql(query: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(WORKING)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


async def main() -> int:
    reset()
    transport = StdioTransport(
        command=".venv/bin/python", args=["mcp_server/server.py"], cwd=str(ROOT)
    )

    async with Client(transport) as c:

        async def call(name, **kw):
            return (await c.call_tool(name, kw)).structured_content

        async def refuses(name, **kw) -> str | None:
            """Return the refusal message, or None if the tool allowed it."""
            try:
                await c.call_tool(name, kw)
                return None
            except Exception as exc:
                return str(exc)

        print("\nRule: a payment cannot be made without human approval")
        req = await call(
            "request_payment_approval",
            ticket_id=101,
            pays_for="invoice",
            ref_id=501,
            amount=840.0,
            reason="Overdue reprint invoice blocking the tee restock",
            requested_by="accounting",
        )
        check("requesting an approval does not pay", req["status"] == "pending")
        check(
            "no payment row was written by the request",
            sql("SELECT * FROM payments") == [],
        )
        check(
            "cash is untouched by the request",
            sql("SELECT balance FROM cash_accounts")[0]["balance"] == 3400.0,
        )
        msg = await refuses("record_payment", approval_id=req["id"], executed_by="accounting")
        check(
            "paying a pending request is refused",
            msg is not None and "human must approve" in msg,
            (msg or "ALLOWED")[:88],
        )

        print("\nRule: an agent cannot approve its own request")
        # decide_approval is never given to an agent (see backend/roles.py).
        # Called here as the dashboard would, naming the human.
        msg = await refuses(
            "decide_approval", approval_id=req["id"], decision="approve", decided_by=""
        )
        check(
            "an approval with no human named is refused",
            msg is not None and "decided_by" in msg,
            (msg or "ALLOWED")[:88],
        )

        decided = await call(
            "decide_approval",
            approval_id=req["id"],
            decision="approve",
            decided_by="Christina McBride",
            note="Clear the blocker so the reprint can ship.",
        )
        check("human approval is recorded", decided["decided_by"] == "Christina McBride")
        check(
            "approval alone still moves no money",
            sql("SELECT balance FROM cash_accounts")[0]["balance"] == 3400.0,
        )

        print("\nRule: an approved payment debits cash and closes the invoice")
        receipt = await call("record_payment", approval_id=req["id"], executed_by="accounting")
        check("balance went 3400 -> 2560", receipt["balance_after"] == 2560.0,
              f"{receipt['balance_before']} -> {receipt['balance_after']}")
        check(
            "cash_accounts actually changed",
            sql("SELECT balance FROM cash_accounts")[0]["balance"] == 2560.0,
        )
        pay = sql("SELECT * FROM payments")
        check("one payment row exists", len(pay) == 1)
        check(
            "the payment names the human who approved it",
            pay and pay[0]["approved_by"] == "Christina McBride",
        )
        check(
            "invoice 501 is now paid",
            sql("SELECT status FROM invoices WHERE id=501")[0]["status"] == "paid",
        )
        msg = await refuses("record_payment", approval_id=req["id"], executed_by="accounting")
        check(
            "the same approval cannot be paid twice",
            msg is not None and "already been paid" in msg,
            (msg or "ALLOWED")[:88],
        )

        print("\nRule: a vendor will not ship while an invoice is open")
        reset()
        msg = await refuses(
            "request_purchase_order_approval",
            ticket_id=103,
            vendor_id=1,
            sku="CC-HOOD-NAVY",
            size="M",
            quantity=12,
            reason="Cover the Yale AI Club shortfall",
            requested_by="inventory",
        )
        check(
            "ordering from a blocked vendor is refused",
            msg is not None and "will not ship" in msg,
            (msg or "ALLOWED")[:88],
        )
        vendors = await call("list_vendors", vendor_id=1)
        v = vendors["result"][0]
        check("list_vendors reports the hold", v["will_ship"] is False,
              f"open invoices {v['open_invoice_ids']}, {v['open_invoice_total']:.2f}")

        print("\nRule: the hold lifts once the invoice is paid")
        a = await call("request_payment_approval", ticket_id=101, pays_for="invoice",
                       ref_id=501, amount=840.0, reason="clear blocker",
                       requested_by="accounting")
        await call("decide_approval", approval_id=a["id"], decision="approve",
                   decided_by="Christina McBride")
        await call("record_payment", approval_id=a["id"], executed_by="accounting")
        v = (await call("list_vendors", vendor_id=1))["result"][0]
        check("vendor 1 will ship now", v["will_ship"] is True,
              f"earliest arrival {v['earliest_arrival_if_ordered_today']}")
        po_req = await call(
            "request_purchase_order_approval", ticket_id=103, vendor_id=1,
            sku="CC-HOOD-NAVY", size="M", quantity=12,
            reason="Cover the Yale AI Club shortfall", requested_by="inventory")
        check("the order can now be requested", po_req["status"] == "pending",
              po_req["summary"][:88])
        check("unit cost came from the pricing table, not a guess",
              po_req["payload"]["unit_cost"] == 22.0 and po_req["amount"] == 264.0)
        check("arrival is shop date + 5 lead days",
              po_req["payload"]["expected_on"] == "2026-09-05")

        print("\nRule: queued money is treated as already spent")
        rent = await call("request_payment_approval", ticket_id=102, pays_for="rent",
                          ref_id=1, amount=2400.0, reason="September rent",
                          requested_by="facilities")
        check("rent fits and queues", rent["status"] == "pending")
        cash = await call("get_cash_balance", account="checking")
        check("a queued payment is reported as committed, not free",
              cash["balance"] == 2560.0 and cash["uncommitted"] == 160.0,
              f"balance {cash['balance']}, uncommitted {cash['uncommitted']}")

        print("\nRule: not enough cash means the payment is refused")
        # Drain the account directly so a real obligation genuinely does not
        # fit. This is test setup; no tool is allowed to do this.
        reset()
        write_sql("UPDATE cash_accounts SET balance = 500.0 WHERE name = 'checking'")
        msg = await refuses("request_payment_approval", ticket_id=102, pays_for="rent",
                            ref_id=1, amount=2400.0, reason="September rent",
                            requested_by="facilities")
        check("a payment larger than the balance is refused at request time",
              msg is not None and "overdraw" in msg, (msg or "ALLOWED")[:88])
        check("nothing was queued", sql("SELECT * FROM approvals") == [])

        print("\nRule: cash is re-checked at the moment of payment")
        # Approve a payment while the money is there, then let the balance
        # fall before it executes. The tool must refuse rather than go negative.
        reset()
        a2 = await call("request_payment_approval", ticket_id=102, pays_for="rent",
                        ref_id=1, amount=2400.0, reason="September rent",
                        requested_by="facilities")
        await call("decide_approval", approval_id=a2["id"], decision="approve",
                   decided_by="Christina McBride")
        write_sql("UPDATE cash_accounts SET balance = 100.0 WHERE name = 'checking'")
        msg = await refuses("record_payment", approval_id=a2["id"],
                            executed_by="accounting")
        check("an approved payment is still refused when the cash is gone",
              msg is not None and "negative balance" in msg, (msg or "ALLOWED")[:88])
        check("the balance never went negative",
              sql("SELECT balance FROM cash_accounts")[0]["balance"] == 100.0)
        check("no payment row was written", sql("SELECT * FROM payments") == [])
        check("the approval is left approved, not executed",
              sql("SELECT status FROM approvals")[0]["status"] == "approved")
        reset()

        print("\nRule: nothing is invented")
        for name, kw, want in [
            ("request_payment_approval",
             dict(ticket_id=102, pays_for="rent", ref_id=1, amount=1200.0,
                  reason="half now", requested_by="facilities"),
             "not 1200.00"),
            ("get_cash_balance", dict(account="savings"), "no cash account"),
            ("get_ticket", dict(ticket_id=999), "no ticket 999"),
            ("update_ticket", dict(ticket_id=101, status="done", note="x",
                                   updated_by="boss"), "not a ticket status"),
        ]:
            msg = await refuses(name, **kw)
            check(f"{name} refuses: {want}", msg is not None and want.split()[-1] in msg,
                  (msg or "ALLOWED")[:88])

        print("\nRule: drafts stay on the board")
        d = await call("draft_customer_message", ticket_id=101,
                       recipient="Tauhid Zaman", subject="Your Bulldog tee",
                       body="The size S reprint is on order.",
                       drafted_by="customer_service")
        check("a draft is stored, not sent", d["status"] == "on_board")
        check("the draft is attached to its ticket",
              sql("SELECT ticket_id FROM message_drafts")[0]["ticket_id"] == 101)

        print("\nRule: the original database is never touched")
        check("original still has the opening balance",
              sqlite3.connect(ORIGINAL).execute(
                  "SELECT balance FROM cash_accounts").fetchone()[0] == 3400.0)
        check("original invoice 501 is still open",
              sqlite3.connect(ORIGINAL).execute(
                  "SELECT status FROM invoices WHERE id=501").fetchone()[0] == "open")

    reset()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print("  FAILED:", f)
    print("working copy reset to the original")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
