"""Shared data types for the Campus Customs agent team.

Two kinds of thing live here: the dependency object passed down through a run
(`ShopDeps`), and the structured outputs the agents must produce. Structured
output is doing real work in this project — an agent that has to fill in
`sources` and `unknowns` cannot round off an answer as easily as one writing
free prose, and the dashboard can render a report without parsing English.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

TicketStatus = Literal["open", "in_progress", "waiting_approval", "blocked", "resolved"]

RoleName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]


@dataclass
class ShopDeps:
    """Carried through a run and into every delegated sub-run.

    `chain` is how a delegation loop is caught: an agent already in the chain
    cannot be delegated to again, so boss -> inventory -> boss is refused
    before it costs a single token.
    """

    run_id: str
    ticket_id: int | None = None
    #: The person at the desk. Recorded on requests so a human can see who
    #: the work is queued for. Agents never act with this authority.
    human_operator: str = "shop operator"
    depth: int = 0
    chain: tuple[str, ...] = field(default_factory=tuple)


class Finding(BaseModel):
    """One fact, and the tool it came from."""

    fact: str = Field(description="A single concrete fact, with its figures.")
    source_tool: str = Field(
        description="The MCP tool that returned it. Never write 'assumed'."
    )


class AgentReport(BaseModel):
    """What a specialist agent hands back to whoever asked it."""

    agent: str
    summary: str = Field(description="Two or three sentences, no padding.")
    findings: list[Finding] = Field(
        default_factory=list,
        description="The facts this answer rests on, each tied to a tool.",
    )
    actions_taken: list[str] = Field(
        default_factory=list,
        description="Changes actually written to the shop, in plain language.",
    )
    approval_ids_requested: list[int] = Field(
        default_factory=list,
        description="Approval requests queued for a human during this work.",
    )
    blocked_by: list[str] = Field(
        default_factory=list,
        description="What stands in the way, if anything does.",
    )
    unknowns: list[str] = Field(
        default_factory=list,
        description=(
            "Anything that could not be established from the tools. Say it "
            "here rather than guessing it into the summary."
        ),
    )
    needs_human: bool = Field(
        default=False,
        description="True when a person has to decide before this can go further.",
    )


class TicketDecision(BaseModel):
    """The boss agent's final word on one ticket."""

    ticket_id: int
    decision: str = Field(description="What the shop is doing about this ticket.")
    rationale: str = Field(
        description="Why, citing the figures the team actually retrieved."
    )
    consulted: list[str] = Field(
        default_factory=list, description="Which agents were brought in."
    )
    findings: list[Finding] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    approval_ids_waiting: list[int] = Field(
        default_factory=list,
        description="Requests now sitting with a human. Nothing moves until decided.",
    )
    customer_draft_ids: list[int] = Field(
        default_factory=list,
        description="Drafts left on the board. Nothing was sent.",
    )
    ticket_status: TicketStatus = Field(
        description="Where the ticket was left. Only 'resolved' if truly finished."
    )
    unknowns: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    """The outcome of running one ticket, for the dashboard and for tests."""

    run_id: str
    ticket_id: int
    ok: bool
    stop_reason: str = Field(
        description="completed, limit_exceeded, model_error, or no_api_key."
    )
    decision: TicketDecision | None = None
    error: str | None = None
    duration_ms: int = 0
    requests: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    delegations: list[str] = Field(default_factory=list)
