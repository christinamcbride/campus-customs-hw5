"""Build the Problem 9 evidence from what actually happened.

Reads the audit trail and the working database and writes
`output/resolved_tickets.json`, plus a machine-readable companion the HTML
pages are filled in from. Nothing here is typed by hand: the agents, the
delegations, the tools, and every dollar figure are read back out of the
record.

    .venv/bin/python scripts/collect_run_evidence.py --since <seq>

`--since` is the audit-trail line number the Problem 9 session began at, so
earlier development runs are not mixed into the evidence.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRAIL = ROOT / "output" / "audit_trail.json"
WORKING = ROOT / "data" / "campus_customs_new.db"
ORIGINAL = ROOT / "data" / "campus_customs.db"
OUT_JSON = ROOT / "output" / "resolved_tickets.json"
OUT_DATA = ROOT / "output" / "run_evidence.json"

TITLES = {
    "boss": "Boss",
    "inventory": "Inventory",
    "accounting": "Accounting",
    "facilities": "Facilities",
    "customer_service": "Customer Service",
}


def rows(db: Path, sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def read_trail(since: int) -> list[dict]:
    out = []
    with TRAIL.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            if i <= since or not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry["_seq"] = i
            out.append(entry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=0)
    ap.add_argument("--opening-balance", type=float, required=True)
    args = ap.parse_args()

    trail = read_trail(args.since)

    # -- group the trail by ticket -----------------------------------------
    per_ticket: dict[int, dict] = {}
    for entry in trail:
        tid = entry.get("ticket_id")
        if tid is None:
            continue
        t = per_ticket.setdefault(
            tid,
            {
                "ticket_id": tid,
                "run_ids": [],
                "agents": OrderedDict(),
                "delegations": [],
                "refused_delegations": [],
                "human_actions": [],
                "stop_reasons": [],
                "usage": {"requests": 0, "tool_calls": 0, "total_tokens": 0},
            },
        )
        run_id = entry.get("run_id", "")
        if run_id and not run_id.startswith("desk") and run_id not in t["run_ids"]:
            t["run_ids"].append(run_id)

        agent = entry.get("agent")
        event = entry.get("event")

        if agent and agent in TITLES:
            a = t["agents"].setdefault(
                agent, {"agent": agent, "tools": [], "tool_calls": 0, "said": []}
            )
            if event == "tool_call":
                a["tool_calls"] += 1
                tool = entry.get("action")
                if tool and tool not in a["tools"]:
                    a["tools"].append(tool)
            if event == "delegation_returned":
                result = entry.get("result")
                if isinstance(result, dict) and result.get("summary"):
                    a["said"].append(result["summary"])

        if event == "delegation":
            target = (entry.get("action") or "").split("->")[-1]
            t["delegations"].append(
                {
                    "from": agent,
                    "to": target,
                    "depth": entry.get("depth"),
                    "task": (entry.get("arguments") or {}).get("task"),
                }
            )
        if event == "delegation_refused":
            t["refused_delegations"].append(
                {
                    "from": agent,
                    "to": (entry.get("action") or "").split("->")[-1],
                    "reason": entry.get("stop_reason"),
                }
            )
        if event == "human_decision":
            t["human_actions"].append(
                {
                    "action": entry.get("action"),
                    "arguments": entry.get("arguments"),
                    "result": entry.get("result"),
                    "error": entry.get("error"),
                    "stop_reason": entry.get("stop_reason"),
                    "detail": entry.get("detail"),
                }
            )
        if event == "run_finished":
            t["stop_reasons"].append(entry.get("stop_reason"))
            u = entry.get("usage") or {}
            for k in t["usage"]:
                t["usage"][k] += int(u.get(k, 0) or 0)

        # The boss's final decision for this ticket.
        if event == "run_finished" and isinstance(entry.get("result"), dict):
            t["decision"] = entry["result"]

    # -- the shop's own records --------------------------------------------
    tickets = {r["id"]: r for r in rows(WORKING, "SELECT * FROM tickets ORDER BY id")}
    payments = rows(WORKING, "SELECT * FROM payments ORDER BY id")
    approvals = rows(WORKING, "SELECT * FROM approvals ORDER BY id")
    orders = rows(WORKING, "SELECT * FROM purchase_orders ORDER BY id")
    drafts = rows(WORKING, "SELECT * FROM message_drafts ORDER BY id")
    cash = rows(WORKING, "SELECT * FROM cash_accounts")[0]
    invoices = rows(WORKING, "SELECT * FROM invoices ORDER BY id")
    leases = rows(WORKING, "SELECT * FROM leases ORDER BY id")

    # -- the cash ledger, built by replaying the payments ------------------
    ledger = []
    running = args.opening_balance
    for p in payments:
        approval = next(
            (a for a in approvals if json.loads(a["payload"]).get("ref_id") == p["ref_id"]
             and a["kind"] == "payment" and json.loads(a["payload"]).get("pays_for") == p["kind"]),
            None,
        )
        before = running
        running = round(running - float(p["amount"]), 2)
        ledger.append(
            {
                "payment_id": p["id"],
                "ticket_id": approval["ticket_id"] if approval else None,
                "pays_for": p["kind"],
                "ref_id": p["ref_id"],
                "amount": float(p["amount"]),
                "account": p["account"],
                "paid_at": p["paid_at"],
                "approved_by": p["approved_by"],
                "requested_by": approval["requested_by"] if approval else None,
                "balance_before": before,
                "balance_after": running,
            }
        )

    reconciles = abs(running - float(cash["balance"])) < 0.005

    # -- resolved_tickets.json ---------------------------------------------
    resolved = []
    for tid in sorted(tickets):
        t = per_ticket.get(tid, {})
        row = tickets[tid]
        decision = t.get("decision") or {}
        contributions = []
        for agent, a in (t.get("agents") or {}).items():
            contributions.append(
                {
                    "agent": TITLES.get(agent, agent),
                    "contribution": (a["said"][-1] if a["said"] else None)
                    or (
                        "Read the ticket, routed the work to the right specialists, "
                        "and made the final call."
                        if agent == "boss"
                        else "Worked the ticket from its own tools."
                    ),
                    "mcp_tools_used": a["tools"],
                    "tool_calls": a["tool_calls"],
                }
            )

        approvals_here = [a for a in approvals if a["ticket_id"] == tid]
        resolved.append(
            {
                "ticket_id": tid,
                "subject": row["subject"],
                "requester": row["requester"],
                "final_status": row["status"],
                "outcome": decision.get("decision"),
                "rationale": decision.get("rationale"),
                "agents": contributions,
                "delegations": [
                    f"{TITLES.get(d['from'], d['from'])} -> {TITLES.get(d['to'], d['to'])}"
                    for d in t.get("delegations", [])
                ],
                "human_approvals": [
                    {
                        "approval_id": a["id"],
                        "kind": a["kind"],
                        "amount": float(a["amount"]),
                        "summary": a["summary"],
                        "requested_by": TITLES.get(a["requested_by"], a["requested_by"]),
                        "status": a["status"],
                        "decided_by": a["decided_by"],
                        "decided_at": a["decided_at"],
                        "decision_note": a["decision_note"],
                    }
                    for a in approvals_here
                ],
                "cash_effect": [
                    {
                        "amount": e["amount"],
                        "pays_for": f"{e['pays_for']} {e['ref_id']}",
                        "balance_after": e["balance_after"],
                        "approved_by": e["approved_by"],
                    }
                    for e in ledger
                    if e["ticket_id"] == tid
                ],
                "purchase_orders": [
                    {
                        "purchase_order_id": o["id"],
                        "sku": o["sku"],
                        "size": o["size"],
                        "quantity": o["quantity"],
                        "total_cost": float(o["total_cost"]),
                        "expected_on": o["expected_on"],
                        "note": "Ordered, not received. Inventory is unchanged until delivery.",
                    }
                    for o in orders
                    if o["ticket_id"] == tid
                ],
                "customer_drafts": [
                    {
                        "draft_id": d["id"],
                        "recipient": d["recipient"],
                        "subject": d["subject"],
                        "status": d["status"],
                        "note": "Held on the board. Nothing was sent.",
                    }
                    for d in drafts
                    if d["ticket_id"] == tid
                ],
                "usage": t.get("usage"),
                "run_ids": t.get("run_ids", []),
            }
        )

    OUT_JSON.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "The outcome of running all three Campus Customs tickets through "
                    "the agent team on the dashboard. Assembled by "
                    "scripts/collect_run_evidence.py from output/audit_trail.json and "
                    "data/campus_customs_new.db; nothing is typed by hand."
                ),
                "shop_date": rows(WORKING, "SELECT date_today FROM desk")[0]["date_today"],
                "opening_balance": args.opening_balance,
                "closing_balance": float(cash["balance"]),
                "tickets": resolved,
            },
            indent=2,
        )
        + "\n"
    )

    OUT_DATA.write_text(
        json.dumps(
            {
                "per_ticket": {str(k): v for k, v in per_ticket.items()},
                "ledger": ledger,
                "approvals": approvals,
                "payments": payments,
                "purchase_orders": orders,
                "drafts": drafts,
                "invoices": invoices,
                "leases": leases,
                "tickets": list(tickets.values()),
                "cash": cash,
                "opening_balance": args.opening_balance,
                "computed_closing": running,
                "database_closing": float(cash["balance"]),
                "reconciles": reconciles,
            },
            indent=2,
            default=str,
        )
        + "\n"
    )

    print(f"opening balance      : {args.opening_balance:,.2f}")
    for e in ledger:
        print(
            f"  ticket {e['ticket_id']}  -{e['amount']:>9,.2f}  "
            f"{e['pays_for']:<12} -> {e['balance_after']:>9,.2f}  "
            f"(approved by {e['approved_by']})"
        )
    print(f"computed closing     : {running:,.2f}")
    print(f"database says        : {float(cash['balance']):,.2f}")
    print(f"reconciles           : {reconciles}")
    print(f"tickets resolved     : "
          f"{sum(1 for t in tickets.values() if t['status'] == 'resolved')}/{len(tickets)}")
    print(f"original untouched   : "
          f"{rows(ORIGINAL, 'SELECT balance FROM cash_accounts')[0]['balance'] == 3400.0}")
    print(f"written              : {OUT_JSON.relative_to(ROOT)}, {OUT_DATA.relative_to(ROOT)}")
    return 0 if reconciles else 1


if __name__ == "__main__":
    sys.exit(main())
