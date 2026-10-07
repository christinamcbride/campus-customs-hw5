"""Exercise every backend route against a running server.

Start the server first, exactly as the assignment specifies:

    cd backend && uvicorn main:app --reload --port 8000

then, from the project root:

    .venv/bin/python scripts/test_routes.py            # everything
    .venv/bin/python scripts/test_routes.py --offline  # skip the agent run

The run resets the shop at the start and again at the end, so it never leaves
the board half-worked.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")
    except urllib.error.URLError as e:
        print(f"\nCannot reach {BASE} — is the server running?  ({e.reason})")
        sys.exit(2)


def main() -> int:
    offline = "--offline" in sys.argv

    print("\nPOST /api/reset — start from the shop's opening state")
    code, body = call("POST", "/api/reset")
    check("reset returns 200", code == 200, str(body)[:90])
    check("three tickets are open again", body.get("tickets_open") == 3)
    check("checking is back to 3400.00", body.get("balance") == 3400.0)

    print("\nGET /api/tickets — the board, with open/resolved")
    code, tickets = call("GET", "/api/tickets")
    check("returns 200", code == 200)
    check("all three tickets are there", len(tickets) == 3,
          ", ".join(str(t["id"]) for t in tickets))
    check("each ticket says whether it is open",
          all({"is_open", "is_resolved"} <= set(t) for t in tickets))
    check("all three start open", all(t["is_open"] for t in tickets))
    check("the ticket's own wording is included",
          any("size S" in (t.get("notes") or "") for t in tickets))

    code, one = call("GET", "/api/tickets/101")
    check("GET /api/tickets/101 returns that ticket", code == 200 and one["id"] == 101)
    code, _ = call("GET", "/api/tickets/999")
    check("an unknown ticket is a 404", code == 404)

    print("\nGET /api/cash — the checking balance")
    code, money = call("GET", "/api/cash")
    check("returns 200", code == 200)
    check("balance is 3400.00", money.get("balance") == 3400.0)
    check("committed and uncommitted are reported",
          money.get("uncommitted") == 3400.0 and money.get("committed_to_pending_approvals") == 0.0)
    code, _ = call("GET", "/api/cash?account=savings")
    check("an unknown account is a 404", code == 404)

    print("\nGET /api/events — the audit trail, shaped for the dashboard")
    code, events = call("GET", "/api/events?limit=5")
    check("returns 200", code == 200)
    check("events carry a seq for polling", all("seq" in e for e in events))
    if events:
        last = events[-1]["seq"]
        code, newer = call("GET", f"/api/events?since={last}")
        check("`since` returns only what is new",
              all(e["seq"] > last for e in newer), f"{len(newer)} new")

    if offline:
        print("\n(skipping the agent run and the approval: --offline)")
    else:
        print("\nPOST /api/tickets/102/run — set the team to work")
        code, started = call("POST", "/api/tickets/102/run?operator=Christina%20McBride")
        check("returns 202 and a run id", code == 202 and "run_id" in started,
              str(started)[:90])
        run_id = started["run_id"]

        code, busy = call("POST", "/api/tickets/101/run")
        check("a second run while one is in flight is refused", code == 409,
              str(busy)[:70])

        print("  waiting for the team...")
        record = None
        for _ in range(90):
            time.sleep(2)
            code, state = call("GET", f"/api/runs/{run_id}")
            if state.get("status") != "running":
                record = state
                break
        check("the run finished", record is not None and record["status"] == "finished",
              str(record)[:90] if record else "timed out")
        if record and record.get("record"):
            r = record["record"]
            check("it stopped cleanly", r["stop_reason"] == "completed", r["stop_reason"])
            check("the boss consulted specialists", bool(r["decision"]["consulted"]),
                  str(r["decision"]["consulted"]))
            check("it stayed inside the ceiling", r["total_tokens"] <= 120_000,
                  f"req={r['requests']} tools={r['tool_calls']} tok={r['total_tokens']}")

        print("\nGET /api/events — what the agents said and which tools they used")
        code, events = call("GET", f"/api/events?run_id={run_id}&limit=500")
        tools_used = {e["tool"] for e in events if e.get("tool")}
        agents = {e["agent"] for e in events if e.get("agent")}
        said = [e for e in events if e.get("said")]
        check("the run's tool calls are visible", len(tools_used) >= 3, str(sorted(tools_used))[:110])
        check("more than one agent appears", len(agents) > 1, str(sorted(agents)))
        check("what the agents said is included", len(said) > 0, f"{len(said)} entries")

        print("\nGET /api/approvals — what the team queued for a human")
        code, approvals = call("GET", "/api/approvals")
        check("returns 200", code == 200)
        pending = [a for a in approvals if a["status"] == "pending"]
        check("the team queued something", bool(pending),
              "; ".join(a["summary"][:70] for a in pending))

        print("\nMoney did NOT move during the agent run")
        code, money = call("GET", "/api/cash")
        check("the balance is untouched", money["balance"] == 3400.0, str(money["balance"]))
        check("the queued amount shows as committed",
              money["committed_to_pending_approvals"] > 0,
              f"{money['committed_to_pending_approvals']:.2f} committed, "
              f"{money['uncommitted']:.2f} free")

        if pending:
            target = pending[0]
            print("\nPOST /api/approvals/{id}/decide — the human clicks, cash moves")
            code, bad = call("POST", f"/api/approvals/{target['id']}/decide",
                             {"decision": "approve", "decided_by": ""})
            check("an approval with no name is rejected by validation", code == 422,
                  str(bad)[:70])

            before = money["balance"]
            code, result = call("POST", f"/api/approvals/{target['id']}/decide",
                                {"decision": "approve", "decided_by": "Christina McBride",
                                 "note": "Approved at the desk."})
            check("the decision returns 200", code == 200, str(result)[:90])
            check("it reports as executed", result.get("executed") is True)
            check("the balance actually fell",
                  result.get("balance_after") == before - target["amount"],
                  f"{before:.2f} -> {result.get('balance_after')}")

            code, money2 = call("GET", "/api/cash")
            check("GET /api/cash agrees", money2["balance"] == result["balance_after"],
                  f"{money2['balance']:.2f}")

            code, again = call("POST", f"/api/approvals/{target['id']}/decide",
                               {"decision": "approve", "decided_by": "Christina McBride"})
            check("the same approval cannot be approved twice", code == 409,
                  str(again.get("detail", ""))[:80])

            code, missing = call("POST", "/api/approvals/9999/decide",
                                 {"decision": "approve", "decided_by": "Christina McBride"})
            check("an unknown approval is a 404", code == 404)

    print("\nPOST /api/reset — put the shop back")
    code, body = call("POST", "/api/reset")
    check("reset returns the shop to 3400.00", body.get("balance") == 3400.0)
    check("three tickets open again", body.get("tickets_open") == 3)
    code, approvals = call("GET", "/api/approvals")
    check("the approval queue was cleared by the reset", approvals == [])
    code, events = call("GET", "/api/events?limit=3")
    check("the audit trail survived the reset", len(events) > 0,
          f"{events[-1]['seq']} entries")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
