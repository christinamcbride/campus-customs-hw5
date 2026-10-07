"""Database access for the Campus Customs MCP server.

Every tool reads the working copy at `data/campus_customs_new.db`. The original
`data/campus_customs.db` is the reset point and is never opened for writing here.

Two things the schema does not do for us, so the connection does them:

* Foreign keys are declared on `tickets` and `invoices` but SQLite ignores them
  unless each connection turns them on.
* Nothing at the storage layer prevents a negative cash balance, so later
  write tools have to enforce that themselves.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

#: The pristine database. Used only as the source for a reset; never written to.
ORIGINAL_DB = DATA_DIR / "campus_customs.db"

#: The working copy every tool reads and (later) writes.
WORKING_DB = DATA_DIR / "campus_customs_new.db"


class DatabaseMissing(RuntimeError):
    """Raised when the working copy has not been created yet."""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the working copy with rows that behave like dicts.

    `check_same_thread=False` because FastMCP runs sync tools on a worker
    thread, which is not the thread that opened the connection.
    """
    if not WORKING_DB.exists():
        raise DatabaseMissing(
            f"{WORKING_DB} does not exist. Create it with: "
            f"cp {ORIGINAL_DB.name} {WORKING_DB.name} (from the data/ folder)."
        )
    conn = sqlite3.connect(WORKING_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_workbench(conn)
        yield conn
    finally:
        conn.close()


def today(conn: sqlite3.Connection) -> str:
    """The shop's own date from `desk.date_today`, as an ISO `YYYY-MM-DD` string.

    The shop runs on its own calendar. Nothing in this project may use the real
    system date to decide what is overdue.
    """
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("The desk table is empty, so the shop has no date.")
    return str(row["date_today"])


# ---------------------------------------------------------------------------
# Tables the agent team needs that the original schema does not provide.
#
# The shop database has nowhere to park a payment that is waiting on a human,
# nowhere to record goods on order, and nowhere to hold a drafted customer
# message. These three tables fill those gaps.
#
# They are created in the *working copy* only, on demand. Resetting the shop
# (`cp data/campus_customs.db data/campus_customs_new.db`) therefore clears
# them along with everything else, which is the behaviour we want: a reset
# should not leave a stale approval queue behind.
# ---------------------------------------------------------------------------

WORKBENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY,
    kind          TEXT    NOT NULL,   -- 'payment' or 'purchase_order'
    ticket_id     INTEGER,
    requested_by  TEXT    NOT NULL,   -- which agent asked
    summary       TEXT    NOT NULL,   -- one line a human can decide from
    amount        REAL    NOT NULL,
    account       TEXT,               -- cash account a payment would draw on
    payload       TEXT    NOT NULL,   -- JSON: the specifics of the request
    status        TEXT    NOT NULL,   -- pending | approved | rejected | executed
    created_at    TEXT    NOT NULL,
    decided_at    TEXT,
    decided_by    TEXT,               -- the human, never an agent
    decision_note TEXT,
    executed_at   TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id            INTEGER PRIMARY KEY,
    approval_id   INTEGER NOT NULL,
    vendor_id     INTEGER NOT NULL,
    sku           TEXT    NOT NULL,
    size          TEXT    NOT NULL,
    quantity      INTEGER NOT NULL,
    unit_cost     REAL    NOT NULL,
    total_cost    REAL    NOT NULL,
    ordered_on    TEXT    NOT NULL,   -- the shop's date, not the real one
    expected_on   TEXT    NOT NULL,   -- ordered_on + vendors.lead_days
    ticket_id     INTEGER,
    status        TEXT    NOT NULL    -- 'placed'
);

CREATE TABLE IF NOT EXISTS message_drafts (
    id         INTEGER PRIMARY KEY,
    ticket_id  INTEGER NOT NULL,
    drafted_by TEXT    NOT NULL,
    recipient  TEXT    NOT NULL,
    subject    TEXT    NOT NULL,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    status     TEXT    NOT NULL       -- always 'on_board'; nothing is ever sent
);
"""


def ensure_workbench(conn: sqlite3.Connection) -> None:
    """Create the agent-team tables in the working copy if they are not there."""
    conn.executescript(WORKBENCH_SCHEMA)
    conn.commit()
