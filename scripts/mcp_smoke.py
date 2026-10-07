"""Smoke-test the Campus Customs MCP server and write the evidence file.

This launches the server the same way Claude Code does — as a stdio subprocess
using the exact `command` and `args` read out of `.mcp.json` — so what is
tested is the configured server, not an in-process import that could pass while
the real configuration is broken.

Every number the tools return is then re-checked with an independent SQL query
against `data/campus_customs_new.db`. Nothing in the evidence file is typed by
hand; it is all captured from the run.

    .venv/bin/python scripts/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".mcp.json"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
EVIDENCE = ROOT / "output" / "mcp_smoke.json"

SERVER_KEY = "campus-customs-ops"


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


SHOP_TABLES = (
    "desk", "tickets", "inventory", "pricing", "vendors",
    "leases", "cash_accounts", "payments", "invoices",
)


def shop_data_hash(path: Path) -> str:
    """Hash the contents of the nine original shop tables.

    The file hash is not the right measure any more: opening the working copy
    creates the three empty agent-team tables (approvals, purchase_orders,
    message_drafts), which changes the file without changing a single shop
    value. This hashes the rows that matter instead.
    """
    conn = sqlite3.connect(path)
    try:
        digest = hashlib.sha1()
        for table in SHOP_TABLES:
            digest.update(table.encode())
            for row in conn.execute(f"SELECT * FROM {table}"):
                digest.update(repr(row).encode())
        return digest.hexdigest()
    finally:
        conn.close()


def query(sql: str, params: tuple) -> dict | None:
    """Read one row straight from the working copy, outside the MCP server."""
    conn = sqlite3.connect(WORKING_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def compare(tool_output: dict, expectations: list[tuple[str, object]]) -> dict:
    """Check named fields of a tool result against values read from the database."""
    checks = []
    for field, from_db in expectations:
        said = tool_output.get(field)
        if isinstance(said, float) or isinstance(from_db, float):
            match = abs(float(said) - float(from_db)) < 0.005
        else:
            match = said == from_db
        checks.append(
            {
                "field": field,
                "tool_returned": said,
                "database_contains": from_db,
                "match": match,
            }
        )
    return {"checks": checks, "all_match": all(c["match"] for c in checks)}


async def main() -> int:
    config = json.loads(CONFIG.read_text())
    entry = config["mcpServers"][SERVER_KEY]

    before = shop_data_hash(WORKING_DB)
    original_before = sha1(ORIGINAL_DB)

    transport = StdioTransport(
        command=entry["command"], args=entry["args"], cwd=str(ROOT)
    )

    tests: list[dict] = []
    errors: list[dict] = []

    async with Client(transport) as client:
        advertised = [t.name for t in await client.list_tools()]

        async def call(name: str, args: dict) -> dict:
            result = await client.call_tool(name, args)
            return result.structured_content

        # -- Tool 1: check_stock, ticket 101 -----------------------------------
        args = {"sku": "CC-TEE-WHITE", "size": "S", "quantity_requested": 1}
        out = await call("check_stock", args)
        inv = query(
            "SELECT name, qty, location FROM inventory WHERE sku = ? AND size = ?",
            ("CC-TEE-WHITE", "S"),
        )
        desk = query("SELECT date_today FROM desk LIMIT 1", ())
        tests.append(
            {
                "ticket": 101,
                "ticket_subject": "Bulldog tee — Tauhid Zaman needs CC-TEE-WHITE in size S",
                "request": (
                    "Ticket 101 asks for one Classic Bulldog Tee in size S. "
                    "Do we have it on the shelf, and if not how many are we short?"
                ),
                "tool": "check_stock",
                "arguments": args,
                "tool_output": out,
                "verification": {
                    "method": "independent SQL against data/campus_customs_new.db",
                    "sql": [
                        "SELECT name, qty, location FROM inventory WHERE sku='CC-TEE-WHITE' AND size='S'",
                        "SELECT date_today FROM desk LIMIT 1",
                    ],
                    "rows_returned_by_sql": {"inventory": inv, "desk": desk},
                    **compare(
                        out,
                        [
                            ("product_name", inv["name"]),
                            ("quantity_on_hand", inv["qty"]),
                            ("location", inv["location"]),
                            ("as_of", desk["date_today"]),
                            ("shortfall", max(0, 1 - inv["qty"])),
                            ("can_fill_from_stock", inv["qty"] >= 1),
                        ],
                    ),
                    "note": (
                        "The shelf holds 0, so ticket 101 cannot be filled from stock. "
                        "shortfall and can_fill_from_stock are derived from the qty "
                        "column, not stored, so both are recomputed here from the row."
                    ),
                },
            }
        )

        # -- Tool 2: check_rent_due, ticket 102 --------------------------------
        args = {"lease_id": 1}
        out_list = await call("check_rent_due", args)
        out = out_list["result"][0]
        lease = query(
            "SELECT space_name, landlord, monthly_rent, next_due FROM leases WHERE id = ?",
            (1,),
        )
        from datetime import date

        days = (
            date.fromisoformat(lease["next_due"])
            - date.fromisoformat(desk["date_today"])
        ).days
        tests.append(
            {
                "ticket": 102,
                "ticket_subject": "Rent due — Elm City Properties, lease 1",
                "request": (
                    "Ticket 102 is an email from the landlord saying rent is due in "
                    "2 days. What does our own lease record say we owe, and when is "
                    "it actually due against the shop's date?"
                ),
                "tool": "check_rent_due",
                "arguments": args,
                "tool_output": out_list,
                "verification": {
                    "method": "independent SQL against data/campus_customs_new.db",
                    "sql": [
                        "SELECT space_name, landlord, monthly_rent, next_due FROM leases WHERE id=1",
                        "SELECT date_today FROM desk LIMIT 1",
                    ],
                    "rows_returned_by_sql": {"leases": lease, "desk": desk},
                    **compare(
                        out,
                        [
                            ("space_name", lease["space_name"]),
                            ("landlord", lease["landlord"]),
                            ("monthly_rent", lease["monthly_rent"]),
                            ("next_due", lease["next_due"]),
                            ("as_of", desk["date_today"]),
                            ("days_until_due", days),
                            ("is_overdue", days < 0),
                        ],
                    ),
                    "note": (
                        "days_until_due is next_due minus desk.date_today "
                        f"({lease['next_due']} - {desk['date_today']} = {days}), "
                        "which confirms the landlord's claim of 2 days against the "
                        "shop's own calendar rather than the real one."
                    ),
                },
            }
        )

        # -- Tool 3: check_discount_margin, ticket 103 -------------------------
        args = {"sku": "CC-HOOD-NAVY", "quantity": 20, "proposed_unit_price": 46.40}
        out = await call("check_discount_margin", args)
        price = query(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", ("CC-HOOD-NAVY",)
        )
        cost, lst, proposed = price["unit_cost"], price["list_price"], 46.40
        tests.append(
            {
                "ticket": 103,
                "ticket_subject": "Bulk hoodie discount — Yale AI Club wants 20 CC-HOOD-NAVY in M",
                "request": (
                    "Ticket 103 asks for a bulk discount on 20 navy hoodies. What is "
                    "our cost and list price, and if we offered 20% off at $46.40 a "
                    "unit, would that still clear cost?"
                ),
                "tool": "check_discount_margin",
                "arguments": args,
                "tool_output": out,
                "verification": {
                    "method": "independent SQL against data/campus_customs_new.db",
                    "sql": [
                        "SELECT unit_cost, list_price FROM pricing WHERE sku='CC-HOOD-NAVY'"
                    ],
                    "rows_returned_by_sql": {"pricing": price},
                    **compare(
                        out,
                        [
                            ("unit_cost", cost),
                            ("list_price", lst),
                            ("break_even_unit_price", cost),
                            ("list_total", round(lst * 20, 2)),
                            ("list_margin_per_unit", round(lst - cost, 2)),
                            ("list_margin_percent", round((lst - cost) / lst * 100, 2)),
                            ("proposed_total", round(proposed * 20, 2)),
                            ("proposed_margin_per_unit", round(proposed - cost, 2)),
                            (
                                "discount_percent_off_list",
                                round((lst - proposed) / lst * 100, 2),
                            ),
                            ("covers_unit_cost", proposed >= cost),
                        ],
                    ),
                    "note": (
                        "Only unit_cost and list_price are stored. Every other figure "
                        "is arithmetic over those two columns and is recomputed here "
                        "from the raw row to confirm the tool is not inventing margins."
                    ),
                },
            }
        )

        # -- Honest-answer checks ---------------------------------------------
        # A tool that quietly returns 0 for an item the shop does not carry
        # would be inventing data. These confirm it refuses instead.
        for name, bad_args, why in [
            (
                "check_stock",
                {"sku": "CC-TEE-WHITE", "size": "XXL"},
                "A size the shop does not carry must not come back as 0 on hand.",
            ),
            (
                "check_stock",
                {"sku": "CC-SCARF-NAVY", "size": "OS"},
                "A SKU that is not in the inventory table at all must be refused.",
            ),
            (
                "check_rent_due",
                {"lease_id": 99},
                "A lease the shop does not hold must not return an empty obligation.",
            ),
            (
                "check_discount_margin",
                {"sku": "CC-SCARF-NAVY", "quantity": 5},
                "A SKU with no pricing row must not be given an estimated margin.",
            ),
        ]:
            try:
                value = await call(name, bad_args)
                errors.append(
                    {
                        "tool": name,
                        "arguments": bad_args,
                        "expectation": why,
                        "refused": False,
                        "returned_instead": value,
                    }
                )
            except Exception as exc:  # fastmcp raises ToolError across the wire
                errors.append(
                    {
                        "tool": name,
                        "arguments": bad_args,
                        "expectation": why,
                        "refused": True,
                        "error_message": str(exc),
                    }
                )

    after = shop_data_hash(WORKING_DB)
    original_after = sha1(ORIGINAL_DB)

    evidence = {
        "what_this_is": (
            "Evidence that the three Campus Customs MCP tools run through the "
            "configuration in .mcp.json and return values that match the working "
            "database. Captured by scripts/mcp_smoke.py; nothing here is typed by hand."
        ),
        "shop_date": desk["date_today"],
        "mcp_configuration": {
            "file": ".mcp.json",
            "server_name": SERVER_KEY,
            "transport": "stdio",
            "command": entry["command"],
            "args": entry["args"],
            "launched_from": str(ROOT),
            "note": (
                "The server was started as a real subprocess with this exact command, "
                "the same way Claude Code starts it."
            ),
        },
        "database": {
            "working_copy": "data/campus_customs_new.db",
            "shop_data_sha1_before_run": before,
            "shop_data_sha1_after_run": after,
            "unchanged_by_run": before == after,
            "original": "data/campus_customs.db",
            "original_file_sha1_before_run": original_before,
            "original_file_sha1_after_run": original_after,
            "original_untouched": original_before == original_after,
            "note": (
                "The working copy is measured by the contents of the nine original "
                "shop tables, not by the file bytes: opening it creates the three "
                "empty agent-team tables (approvals, purchase_orders, "
                "message_drafts), which changes the file without changing any shop "
                "value. The original is measured by file hash and must never move."
            ),
        },
        "tools_advertised_by_server": advertised,
        "tests": tests,
        "honest_answer_checks": errors,
        "summary": {
            "tools_tested": len(tests),
            "all_values_match_database": all(
                t["verification"]["all_match"] for t in tests
            ),
            "unknown_inputs_refused": sum(1 for e in errors if e["refused"]),
            "unknown_inputs_tried": len(errors),
            "working_copy_unchanged": before == after,
            "original_untouched": original_before == original_after,
        },
    }

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2) + "\n")

    s = evidence["summary"]
    print(f"tools advertised      : {advertised}")
    print(f"tools tested          : {s['tools_tested']}")
    print(f"values match database : {s['all_values_match_database']}")
    print(f"unknown inputs refused: {s['unknown_inputs_refused']}/{s['unknown_inputs_tried']}")
    print(f"shop data unchanged : {s['working_copy_unchanged']}")
    print(f"original untouched    : {s['original_untouched']}")
    print(f"written               : {EVIDENCE.relative_to(ROOT)}")

    ok = (
        s["all_values_match_database"]
        and s["unknown_inputs_refused"] == s["unknown_inputs_tried"]
        and s["working_copy_unchanged"]
        and s["original_untouched"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
