"""FastAPI backend for the Campus Customs operations dashboard.

Run it from this directory:

    cd backend
    uvicorn main:app --reload --port 8000

Two things worth knowing before reading the routes.

**No shop data is read or written here directly.** Every figure comes back
through the MCP server, the same door the agents use. `main.py` never opens
the SQLite file, so the rules enforced in the tools cannot be sidestepped by
calling the API instead of an agent. The one exception is `POST /api/reset`,
which copies a file and is not a shop operation at all.

**The approval route is the only place money moves.** Agents can queue a
payment and nothing more. A person clicking Approve in the dashboard is what
turns a request into a cash change, and their name goes into
`payments.approved_by`.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

# Allow `uvicorn main:app` from inside backend/ as well as
# `uvicorn backend.main:app` from the project root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from backend import audit  # noqa: E402
from backend.config import MODEL_NAME, AgentUnavailable, get_settings  # noqa: E402
from backend.mcp_link import MCPLink, ToolRefused  # noqa: E402
from backend.models import RunRecord  # noqa: E402
from backend.roles import ROLES  # noqa: E402
from backend.team import MAX_DELEGATION_DEPTH, TICKET_LIMITS, Team  # noqa: E402

ORIGINAL_DB = _ROOT / "data" / "campus_customs.db"
WORKING_DB = _ROOT / "data" / "campus_customs_new.db"

#: Statuses that mean the shop is finished with a ticket.
CLOSED_STATUSES = {"resolved"}

link = MCPLink()

#: Run records kept in memory for the dashboard to poll. Runs are started in
#: the background so a 30-second agent conversation does not sit on an open
#: HTTP request.
RUNS: dict[str, dict[str, Any]] = {}

#: One ticket at a time. Two runs would race on the same approval queue and
#: could queue the same payment twice.
RUN_LOCK = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await link.open()
    try:
        yield
    finally:
        await link.close()


app = FastAPI(
    title="Campus Customs Operations",
    version="1.0",
    summary="The desk behind the agent team: the board, the money, and the approvals.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _refused(exc: ToolRefused) -> HTTPException:
    """Turn a tool's refusal into a 409 with the tool's own wording.

    "A human must approve a payment before it can be made" is a better answer
    than "Internal Server Error", and it is the shop's rule talking.
    """
    return HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------


class TicketView(BaseModel):
    """One ticket as the dashboard shows it."""

    id: int
    type: str
    requester: str
    subject: str
    status: str
    is_open: bool = Field(description="False once the shop is finished with it.")
    is_resolved: bool
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    notes: str | None = None
    created_at: str


@app.get("/api/tickets", response_model=list[TicketView], tags=["board"])
async def list_tickets() -> list[TicketView]:
    """Every ticket on the board, with whether it is still open."""
    try:
        rows = await link.call("list_tickets", status=None)
    except ToolRefused as exc:
        raise _refused(exc)
    return [
        TicketView(
            **row,
            is_open=row["status"] not in CLOSED_STATUSES,
            is_resolved=row["status"] in CLOSED_STATUSES,
        )
        for row in rows
    ]


@app.get("/api/tickets/{ticket_id}", response_model=TicketView, tags=["board"])
async def get_ticket(ticket_id: int) -> TicketView:
    """One ticket in full, including the requester's own words."""
    try:
        row = await link.call("get_ticket", ticket_id=ticket_id)
    except ToolRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return TicketView(
        **row,
        is_open=row["status"] not in CLOSED_STATUSES,
        is_resolved=row["status"] in CLOSED_STATUSES,
    )


class ResolveBody(BaseModel):
    resolved_by: str = Field(min_length=1)
    note: str = "Closed at the desk."


@app.post("/api/tickets/{ticket_id}/resolve", response_model=TicketView, tags=["board"])
async def resolve_ticket(ticket_id: int, body: ResolveBody) -> TicketView:
    """Close a ticket off once the work behind it is actually done.

    The agents set a ticket's status themselves as they work it — usually to
    `waiting_approval` or `blocked`, because a plan is not a finished job.
    Closing it is the person's call, and refused while anything is still
    queued for them to decide: a ticket cannot be finished while the shop is
    still waiting on a signature.
    """
    try:
        approvals = await link.call("list_approvals", status="pending")
    except ToolRefused as exc:
        raise _refused(exc)

    waiting = [a for a in approvals if a.get("ticket_id") == ticket_id]
    if waiting:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ticket {ticket_id} still has {len(waiting)} request waiting on a "
                "decision. Approve or reject it before closing the ticket."
            ),
        )

    try:
        await link.call(
            "update_ticket",
            ticket_id=ticket_id,
            status="resolved",
            note=body.note,
            updated_by=body.resolved_by,
        )
        row = await link.call("get_ticket", ticket_id=ticket_id)
    except ToolRefused as exc:
        raise _refused(exc)

    audit.record(
        "human_decision",
        run_id=f"desk-ticket-{ticket_id}",
        ticket_id=ticket_id,
        action="resolve_ticket",
        arguments={"resolved_by": body.resolved_by},
        stop_reason="resolved",
    )
    return TicketView(**row, is_open=False, is_resolved=True)


# ---------------------------------------------------------------------------
# Running the agent team
# ---------------------------------------------------------------------------


class RunStarted(BaseModel):
    run_id: str
    ticket_id: int
    status: Literal["running"] = "running"
    poll: str = Field(description="Where to read the result once it finishes.")
    events: str = Field(description="Where to watch the team work in the meantime.")


async def _work_ticket(key: str, ticket_id: int, operator: str) -> None:
    """Run the team in the background and park the result for polling."""
    async with RUN_LOCK:
        try:
            async with Team(human_operator=operator) as team:
                # The API's key is the audit run id, so /api/events?run_id=
                # filters on exactly the run the dashboard is watching.
                record = await team.run_ticket(ticket_id, run_id=key)
            RUNS[key] = {
                "status": "finished",
                "ticket_id": ticket_id,
                "record": record.model_dump(),
            }
        except AgentUnavailable as exc:
            RUNS[key] = {
                "status": "failed",
                "ticket_id": ticket_id,
                "error": str(exc),
                "stop_reason": "no_api_key",
            }
        except Exception as exc:  # the dashboard should see this, not a silent stall
            RUNS[key] = {
                "status": "failed",
                "ticket_id": ticket_id,
                "error": f"{type(exc).__name__}: {exc}",
                "stop_reason": "model_error",
            }


@app.post(
    "/api/tickets/{ticket_id}/run",
    response_model=RunStarted,
    status_code=202,
    tags=["agents"],
)
async def run_ticket(ticket_id: int, operator: str = "shop operator") -> RunStarted:
    """Set the agent team to work on one ticket.

    Returns straight away with a run id. The conversation takes tens of
    seconds and the dashboard should watch `/api/events` while it happens
    rather than hold an HTTP request open.

    Nothing this run does can move money. The team can queue a payment for
    approval; only `/api/approvals/{id}/decide` pays it.
    """
    if not get_settings().ai_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "PORTKEY_API_KEY is not set, so the agent team cannot run. Put it "
                "in PORTKEY_API_KEY.env at the project root."
            ),
        )
    try:
        await link.call("get_ticket", ticket_id=ticket_id)
    except ToolRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if RUN_LOCK.locked():
        raise HTTPException(
            status_code=409,
            detail="A ticket is already being worked. Wait for it to finish.",
        )

    key = uuid.uuid4().hex[:12]
    RUNS[key] = {"status": "running", "ticket_id": ticket_id}
    asyncio.create_task(_work_ticket(key, ticket_id, operator))
    return RunStarted(
        run_id=key,
        ticket_id=ticket_id,
        poll=f"/api/runs/{key}",
        events="/api/events",
    )


@app.get("/api/runs/{run_id}", tags=["agents"])
async def get_run(run_id: str) -> dict[str, Any]:
    """The outcome of a run: the boss's decision, usage, and why it stopped."""
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}.")
    return record


@app.get("/api/runs", tags=["agents"])
async def list_runs() -> dict[str, Any]:
    """Every run this server has started, newest last."""
    return {"runs": [{"run_id": k, **v} for k, v in RUNS.items()]}


# ---------------------------------------------------------------------------
# What the team is doing
# ---------------------------------------------------------------------------


class AgentEvent(BaseModel):
    """One line of the audit trail, shaped for the dashboard."""

    seq: int = Field(description="Position in the trail. Pass it back as `since`.")
    time: str
    event: str
    run_id: str
    agent: str | None = None
    ticket_id: int | None = None
    action: str | None = Field(
        default=None,
        description="The raw action — a tool name, or `delegate->accounting`.",
    )
    tool: str | None = Field(default=None, description="The MCP tool, when it was one.")
    arguments: Any = None
    result: Any = None
    said: str | None = Field(
        default=None,
        description="What the agent reported back, when this event carried a report.",
    )
    depth: int | None = None
    stop_reason: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None


TOOL_EVENTS = {"tool_call"}


def _said(entry: dict[str, Any]) -> str | None:
    """Pull the agent's own words out of a report or decision, if there are any."""
    result = entry.get("result")
    if isinstance(result, dict):
        for key in ("summary", "decision"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if entry.get("event") == "delegation":
        args = entry.get("arguments")
        if isinstance(args, dict) and isinstance(args.get("task"), str):
            return args["task"]
    return None


@app.get("/api/events", response_model=list[AgentEvent], tags=["agents"])
async def list_events(
    since: int = Query(0, ge=0, description="Return only events after this seq."),
    limit: int = Query(200, ge=1, le=2000),
    run_id: str | None = None,
) -> list[AgentEvent]:
    """Recent agent activity: who acted, what they said, and which tools they used.

    Read straight from `output/audit_trail.json`, so it is the same record an
    auditor would read afterwards rather than a second, prettier account of
    events. Poll with the last `seq` you saw to get only what is new.
    """
    trail = audit.read_trail()
    events: list[AgentEvent] = []
    for i, entry in enumerate(trail, start=1):
        if i <= since:
            continue
        if run_id and entry.get("run_id") != run_id:
            continue
        events.append(
            AgentEvent(
                seq=i,
                time=entry.get("time", ""),
                event=entry.get("event", ""),
                run_id=entry.get("run_id", ""),
                agent=entry.get("agent"),
                ticket_id=entry.get("ticket_id"),
                action=entry.get("action"),
                tool=entry.get("action") if entry.get("event") in TOOL_EVENTS else None,
                arguments=entry.get("arguments"),
                result=entry.get("result"),
                said=_said(entry),
                depth=entry.get("depth"),
                stop_reason=entry.get("stop_reason"),
                error=entry.get("error"),
                duration_ms=entry.get("duration_ms"),
                usage=entry.get("usage"),
            )
        )
    return events[-limit:]


# ---------------------------------------------------------------------------
# Approvals — the only place money moves
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    decided_by: str = Field(
        min_length=1,
        description="The person at the desk. Recorded in payments.approved_by.",
    )
    note: str = ""


class DecisionResult(BaseModel):
    approval_id: int
    kind: str
    decision: str
    decided_by: str
    executed: bool = Field(description="True when the cash or the order actually moved.")
    receipt: dict[str, Any] | None = None
    balance_after: float | None = None
    message: str


@app.get("/api/approvals", tags=["approvals"])
async def list_approvals(status: str | None = None) -> list[dict[str, Any]]:
    """Requests the agents have queued, and what has been decided about them."""
    try:
        return await link.call("list_approvals", status=status)
    except ToolRefused as exc:
        raise _refused(exc)


@app.post(
    "/api/approvals/{approval_id}/decide",
    response_model=DecisionResult,
    tags=["approvals"],
)
async def decide(approval_id: int, body: Decision) -> DecisionResult:
    """Approve or reject a queued request — and carry it out if approved.

    This is the human's route. An agent has prepared a payment or an order and
    gone no further; clicking Approve here is what debits the account or
    places the order, and `decided_by` is written into the payment record.

    Approving is still not a guarantee. The payment tool re-reads the balance
    at this moment, and refuses with a 409 rather than overdrawing the account
    if the money has gone since the request was queued. In that case the
    approval stays approved and nothing is written.
    """
    try:
        pending = await link.call("list_approvals")
    except ToolRefused as exc:
        raise _refused(exc)

    match = next((a for a in pending if a["id"] == approval_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No approval {approval_id}.")

    try:
        decided = await link.call(
            "decide_approval",
            approval_id=approval_id,
            decision=body.decision,
            decided_by=body.decided_by,
            note=body.note,
        )
    except ToolRefused as exc:
        raise _refused(exc)

    audit.record(
        "human_decision",
        run_id=f"desk-{approval_id}",
        agent=None,
        ticket_id=match.get("ticket_id"),
        action=f"{body.decision}_approval",
        arguments={"approval_id": approval_id, "decided_by": body.decided_by},
        detail=match.get("summary"),
    )

    if body.decision == "reject":
        return DecisionResult(
            approval_id=approval_id,
            kind=match["kind"],
            decision="rejected",
            decided_by=body.decided_by,
            executed=False,
            message="Rejected. Nothing was paid or ordered.",
        )

    tool = "record_payment" if match["kind"] == "payment" else "place_purchase_order"
    try:
        receipt = await link.call(
            tool, approval_id=approval_id, executed_by=body.decided_by
        )
    except ToolRefused as exc:
        # Approved, but the shop's rules stopped it. The approval stays
        # approved so it can be retried; nothing was written.
        audit.record(
            "human_decision",
            run_id=f"desk-{approval_id}",
            action=tool,
            error=str(exc),
            stop_reason="refused_at_execution",
            ticket_id=match.get("ticket_id"),
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Approved, but the shop refused to carry it out: {exc} "
                "The approval is still approved and nothing was written."
            ),
        )

    audit.record(
        "human_decision",
        run_id=f"desk-{approval_id}",
        action=tool,
        ticket_id=match.get("ticket_id"),
        result=receipt,
        stop_reason="executed",
    )

    balance = receipt.get("balance_after") if isinstance(receipt, dict) else None
    moved = (
        f"Paid {receipt['amount']:.2f}; {receipt['account']} is now "
        f"{receipt['balance_after']:.2f}."
        if match["kind"] == "payment"
        else (
            f"Ordered {receipt['quantity']} x {receipt['sku']} ({receipt['size']}), "
            f"expected {receipt['expected_on']}. No cash moved; "
            "inventory is unchanged until the delivery arrives."
        )
    )
    return DecisionResult(
        approval_id=approval_id,
        kind=match["kind"],
        decision="approved",
        decided_by=body.decided_by,
        executed=True,
        receipt=receipt,
        balance_after=balance,
        message=moved,
    )


# ---------------------------------------------------------------------------
# Money and the board's other artefacts
# ---------------------------------------------------------------------------


@app.get("/api/cash", tags=["money"])
async def cash(account: str = "checking") -> dict[str, Any]:
    """The checking balance, and how much of it is already queued for approval.

    `uncommitted` is the number to act on. `balance` ignores payments already
    waiting on a human, and two payments that each fit may not fit together.
    """
    try:
        return await link.call("get_cash_balance", account=account)
    except ToolRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/drafts", tags=["board"])
async def drafts(ticket_id: int | None = None) -> list[dict[str, Any]]:
    """Customer messages the team has drafted. Nothing here has been sent."""
    try:
        return await link.call("list_message_drafts", ticket_id=ticket_id)
    except ToolRefused as exc:
        raise _refused(exc)


@app.get("/api/purchase-orders", tags=["board"])
async def purchase_orders(ticket_id: int | None = None) -> list[dict[str, Any]]:
    """Restock orders placed, with the arrival date each one is expected on."""
    try:
        return await link.call("list_purchase_orders", ticket_id=ticket_id)
    except ToolRefused as exc:
        raise _refused(exc)


# ---------------------------------------------------------------------------
# Resetting the shop
# ---------------------------------------------------------------------------


class ResetResult(BaseModel):
    reset: bool
    tickets_open: int
    balance: float
    message: str


@app.post("/api/reset", response_model=ResetResult, tags=["admin"])
async def reset() -> ResetResult:
    """Put the shop back to its opening state for a fresh run.

    Copies `data/campus_customs.db` over `data/campus_customs_new.db`. This is
    a file operation rather than a shop operation, so it is the one route that
    does not go through MCP — there is no tool for it, and there should not be
    one: nothing an agent can reach should be able to erase the record of what
    it did.

    The approval queue, placed orders, and drafts live in the working copy and
    are cleared along with everything else. The audit trail is a separate file
    and is **not** touched: it is append-only across resets by design.
    """
    if RUN_LOCK.locked():
        raise HTTPException(
            status_code=409,
            detail="A ticket is being worked right now. Wait for it to finish.",
        )
    if not ORIGINAL_DB.exists():
        raise HTTPException(status_code=500, detail="The original database is missing.")

    # Drop the live connection first: the file is about to be replaced
    # underneath it.
    await link.close()
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    await link.open()
    RUNS.clear()

    tickets = await link.call("list_tickets", status="open")
    balance = await link.call("get_cash_balance", account="checking")
    audit.record(
        "shop_reset",
        run_id="desk-reset",
        action="reset_database",
        detail="Working copy restored from data/campus_customs.db",
    )
    return ResetResult(
        reset=True,
        tickets_open=len(tickets),
        balance=balance["balance"],
        message=(
            f"Shop reset: {len(tickets)} open tickets, "
            f"{balance['balance']:.2f} in checking. The audit trail was kept."
        ),
    )


# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["admin"])
async def health() -> dict[str, Any]:
    """Whether the pieces are wired up: MCP, the key, the team, the limits."""
    return {
        "ok": True,
        "model": MODEL_NAME,
        "agent_team_ready": get_settings().ai_configured,
        "agents": sorted(ROLES),
        "mcp_tools": await link.tool_names(),
        "limits": {
            "requests": TICKET_LIMITS.request_limit,
            "tool_calls": TICKET_LIMITS.tool_calls_limit,
            "total_tokens": TICKET_LIMITS.total_tokens_limit,
            "delegation_depth": MAX_DELEGATION_DEPTH,
        },
    }
