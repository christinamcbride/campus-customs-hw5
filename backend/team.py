"""The Campus Customs agent team.

Five PydanticAI agents over one shared MCP connection. Every shop fact any of
them knows arrives through that connection — there is no second data layer,
and none of these agents can open the database directly.

Three things are enforced here rather than hoped for in a prompt:

* **Tool scope.** Each agent sees only the MCP tools its role allows, and
  `decide_approval` is on nobody's list.
* **Delegation that terminates.** Any agent may delegate to any other, but
  the chain is capped and an agent already in it cannot be re-entered, so
  boss -> inventory -> boss is refused before it costs a token.
* **A ceiling on the whole ticket.** Requests, tool calls, and tokens are
  counted across the boss and every agent it pulls in, not per agent, so a
  ticket cannot become expensive by spreading the cost around.

Every step is appended to `output/audit_trail.json`.
"""

from __future__ import annotations

import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import replace
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.usage import RunUsage, UsageLimits

from . import audit
from .config import MODEL_NAME, PROJECT_ROOT, AgentUnavailable, build_model
from .models import AgentReport, RunRecord, ShopDeps, TicketDecision
from .roles import ROLES, Role, assert_no_agent_can_approve

# ---------------------------------------------------------------------------
# Limits. Multi-agent chats burn tokens fast; these are the brakes.
# ---------------------------------------------------------------------------

#: How deep a delegation chain may go. boss -> specialist -> specialist, stop.
MAX_DELEGATION_DEPTH = 2

#: Ceiling for one ticket, shared by every agent working it.
TICKET_LIMITS = UsageLimits(
    request_limit=24,
    tool_calls_limit=40,
    total_tokens_limit=120_000,
)

#: Retries on a malformed structured output, per agent.
OUTPUT_RETRIES = 2

#: The two agents that can put a request in front of a human. Both are
#: held to finishing the job rather than describing it — see
#: `_require_a_queued_request`.
MONEY_ROLES = frozenset({"facilities", "accounting"})

MCP_COMMAND = ".venv/bin/python"
MCP_ARGS = ["mcp_server/server.py"]


class Team:
    """The five agents, their shared MCP connection, and the run loop.

    Use it as an async context manager so the MCP subprocess is started once
    and reused, rather than being spawned per agent or per tool call:

        async with Team() as team:
            record = await team.run_ticket(101)
    """

    def __init__(
        self, human_operator: str = "shop operator", model: Any = None
    ) -> None:
        assert_no_agent_can_approve()
        self.human_operator = human_operator
        # Only the tests pass a model: a FunctionModel lets the delegation and
        # usage ceilings be proved without spending tokens. Everything else
        # gets gpt-6-luna and nothing else.
        self._model_override = model
        self._stack = AsyncExitStack()
        self._toolset: MCPToolset | None = None
        self.agents: dict[str, Agent[ShopDeps, Any]] = {}

    # -- lifecycle --------------------------------------------------------

    async def __aenter__(self) -> "Team":
        client = Client(
            StdioTransport(
                command=MCP_COMMAND, args=MCP_ARGS, cwd=str(PROJECT_ROOT)
            )
        )
        self._toolset = MCPToolset(client, process_tool_call=self._audited_tool_call)
        self._build_agents()
        await self._stack.enter_async_context(self._toolset)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    # -- auditing ---------------------------------------------------------

    async def _audited_tool_call(
        self,
        ctx: RunContext[ShopDeps],
        call_tool,
        name: str,
        args: dict[str, Any],
    ):
        """Wrap every MCP tool call so the trail records it, pass or fail."""
        started = time.monotonic()
        agent_name = self._agent_for_context(ctx)
        try:
            result = await call_tool(name, args)
        except Exception as exc:
            audit.record(
                "tool_call",
                run_id=ctx.deps.run_id,
                agent=agent_name,
                ticket_id=ctx.deps.ticket_id,
                action=name,
                arguments=args,
                error=f"{type(exc).__name__}: {exc}",
                depth=ctx.deps.depth,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            raise
        audit.record(
            "tool_call",
            run_id=ctx.deps.run_id,
            agent=agent_name,
            ticket_id=ctx.deps.ticket_id,
            action=name,
            arguments=args,
            result=_result_payload(result),
            depth=ctx.deps.depth,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    @staticmethod
    def _agent_for_context(ctx: RunContext[ShopDeps]) -> str:
        """Which agent is acting: the last link in the delegation chain."""
        return ctx.deps.chain[-1] if ctx.deps.chain else "boss"

    # -- construction -----------------------------------------------------

    def _build_agents(self) -> None:
        model = self._model_override or build_model(MODEL_NAME)
        for role in ROLES.values():
            self.agents[role.name] = self._build_agent(role, model)

    def _build_agent(self, role: Role, model) -> Agent[ShopDeps, Any]:
        allowed = role.tools
        assert self._toolset is not None
        scoped = self._toolset.filtered(lambda ctx, td, _a=allowed: td.name in _a)

        agent = Agent(
            model,
            deps_type=ShopDeps,
            output_type=TicketDecision if role.name == "boss" else AgentReport,
            instructions=role.prompt,
            toolsets=[scoped],
            retries=OUTPUT_RETRIES,
            name=role.name,
        )

        @agent.instructions
        def working_context(ctx: RunContext[ShopDeps]) -> str:
            lines = [f"You are the {role.title} agent. Your name is `{role.name}`."]
            if ctx.deps.ticket_id is not None:
                lines.append(f"You are working ticket {ctx.deps.ticket_id}.")
            lines.append(
                "The person at the desk is "
                f"{ctx.deps.human_operator}. They approve payments and orders; "
                "you never do."
            )
            if ctx.deps.chain:
                lines.append(
                    "This work reached you via: " + " -> ".join(ctx.deps.chain) + "."
                )
            remaining = MAX_DELEGATION_DEPTH - ctx.deps.depth
            lines.append(
                f"You may delegate {remaining} more level(s) deep."
                if remaining > 0
                else "You are at the delegation limit. Answer from your own tools."
            )
            return " ".join(lines)

        self._attach_delegation(agent, role)
        if role.name in MONEY_ROLES:
            self._require_a_queued_request(agent, role)
        return agent

    @staticmethod
    def _require_a_queued_request(agent: Agent[ShopDeps, Any], role: Role) -> None:
        """Make the two money agents finish the job they were asked to do.

        Both facilities and accounting were told in their prompts to queue a
        request rather than report that one is needed, and both ignored it
        often enough to matter: on two consecutive runs of ticket 102,
        facilities read the lease, confirmed $2,400 was owed and affordable,
        and handed back a report with an empty approval list — leaving the
        human to do the work the agent was asked to do.

        A prompt could not be relied on, so this is a validator. An agent that
        says a person needs to act must either have queued something for them
        or say what stopped it. Saying neither is sent back once.
        """

        @agent.output_validator
        def must_queue_or_explain(
            ctx: RunContext[ShopDeps], report: AgentReport
        ) -> AgentReport:
            undecided = (
                report.needs_human
                and not report.approval_ids_requested
                and not report.blocked_by
                and not report.unknowns
            )
            if undecided:
                audit.record(
                    "output_rejected",
                    run_id=ctx.deps.run_id,
                    agent=role.name,
                    ticket_id=ctx.deps.ticket_id,
                    action="must_queue_or_explain",
                    stop_reason="nothing_queued",
                    detail=report.summary,
                )
                raise ModelRetry(
                    "You reported that a person needs to act, but you queued "
                    "nothing for them and named nothing blocking you. Either "
                    "call request_payment_approval (or "
                    "request_purchase_order_approval) so there is something "
                    "concrete on the board to decide, or put the reason you "
                    "cannot in `blocked_by`. A report that says a payment is "
                    "needed without queueing it leaves the work undone."
                )
            return report

    def _attach_delegation(self, agent: Agent[ShopDeps, Any], role: Role) -> None:
        peer_list = "\n".join(
            f"- `{name}`: {ROLES[name].blurb}" for name in sorted(role.peers)
        )

        description = (
            "Hand one specific task to another agent and get their report back.\n\n"
            "Who you can ask:\n" + peer_list + "\n\n"
            "Give a concrete task, not the whole ticket — the other agent has "
            "its own tools and will come back with findings tied to them. "
            "Arguments: to_agent (one of the names above), task (what you need "
            "from them, in a sentence or two)."
        )

        @agent.tool(description=description)
        async def delegate(
            ctx: RunContext[ShopDeps], to_agent: str, task: str
        ) -> dict[str, Any]:
            target = to_agent.strip().lower()
            started = time.monotonic()

            if target not in role.peers:
                audit.record(
                    "delegation_refused",
                    run_id=ctx.deps.run_id,
                    agent=role.name,
                    ticket_id=ctx.deps.ticket_id,
                    action=f"delegate->{target}",
                    depth=ctx.deps.depth,
                    stop_reason="not_a_peer",
                )
                return {
                    "refused": f"{to_agent!r} is not an agent you can delegate to.",
                    "available": sorted(role.peers),
                }
            if ctx.deps.depth >= MAX_DELEGATION_DEPTH:
                audit.record(
                    "delegation_refused",
                    run_id=ctx.deps.run_id,
                    agent=role.name,
                    ticket_id=ctx.deps.ticket_id,
                    action=f"delegate->{target}",
                    depth=ctx.deps.depth,
                    stop_reason="depth_limit",
                )
                return {
                    "refused": (
                        f"Delegation is capped at {MAX_DELEGATION_DEPTH} levels and "
                        "you are at the limit. Answer from your own tools, or say "
                        "in `unknowns` what you could not establish."
                    )
                }
            if target in ctx.deps.chain or target == role.name:
                audit.record(
                    "delegation_refused",
                    run_id=ctx.deps.run_id,
                    agent=role.name,
                    ticket_id=ctx.deps.ticket_id,
                    action=f"delegate->{target}",
                    depth=ctx.deps.depth,
                    stop_reason="would_loop",
                )
                return {
                    "refused": (
                        f"`{target}` is already working this chain "
                        f"({' -> '.join(ctx.deps.chain) or role.name}). Sending it "
                        "back would loop. Decide with what you have."
                    )
                }

            audit.record(
                "delegation",
                run_id=ctx.deps.run_id,
                agent=role.name,
                ticket_id=ctx.deps.ticket_id,
                action=f"delegate->{target}",
                arguments={"task": task},
                depth=ctx.deps.depth,
            )

            child_deps = replace(
                ctx.deps,
                depth=ctx.deps.depth + 1,
                chain=ctx.deps.chain + (target,),
            )
            # Sharing ctx.usage is what makes TICKET_LIMITS a ceiling for the
            # whole ticket instead of a per-agent allowance.
            result = await self.agents[target].run(
                task,
                deps=child_deps,
                usage=ctx.usage,
                usage_limits=TICKET_LIMITS,
            )
            report = result.output
            audit.record(
                "delegation_returned",
                run_id=ctx.deps.run_id,
                agent=target,
                ticket_id=ctx.deps.ticket_id,
                action=f"{role.name}<-{target}",
                result=report.model_dump() if hasattr(report, "model_dump") else report,
                depth=child_deps.depth,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return report.model_dump() if hasattr(report, "model_dump") else {"report": report}

    # -- running ----------------------------------------------------------

    async def run_ticket(
        self,
        ticket_id: int,
        instruction: str | None = None,
        run_id: str | None = None,
    ) -> RunRecord:
        """Work one ticket, from the boss down, and record what happened.

        `run_id` can be supplied by the caller so the id the dashboard holds
        is the same one written to the audit trail. Two ids for one run would
        mean the dashboard could not filter the trail it is displaying.
        """
        run_id = run_id or uuid.uuid4().hex[:12]
        deps = ShopDeps(
            run_id=run_id,
            ticket_id=ticket_id,
            human_operator=self.human_operator,
            chain=("boss",),
        )
        usage = RunUsage()
        started = time.monotonic()

        audit.record(
            "run_started",
            run_id=run_id,
            agent="boss",
            ticket_id=ticket_id,
            action="run_ticket",
            detail=f"model={MODEL_NAME}, limits={_limits_detail()}",
        )

        prompt = instruction or (
            f"Work ticket {ticket_id}. Read it first, bring in whoever actually "
            "owns the ground it covers, and decide what the shop does. Leave the "
            "ticket in the right status."
        )

        try:
            result = await self.agents["boss"].run(
                prompt, deps=deps, usage=usage, usage_limits=TICKET_LIMITS
            )
        except UsageLimitExceeded as exc:
            return self._finish(
                run_id, ticket_id, started, usage, "limit_exceeded", error=str(exc)
            )
        except AgentUnavailable as exc:
            return self._finish(
                run_id, ticket_id, started, usage, "no_api_key", error=str(exc)
            )
        except Exception as exc:
            return self._finish(
                run_id,
                ticket_id,
                started,
                usage,
                "model_error",
                error=f"{type(exc).__name__}: {exc}",
            )

        return self._finish(
            run_id, ticket_id, started, usage, "completed", decision=result.output
        )

    def _finish(
        self,
        run_id: str,
        ticket_id: int,
        started: float,
        usage: RunUsage,
        stop_reason: str,
        decision: TicketDecision | None = None,
        error: str | None = None,
    ) -> RunRecord:
        duration = int((time.monotonic() - started) * 1000)
        usage_summary = {
            "requests": usage.requests,
            "tool_calls": usage.tool_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
        audit.record(
            "run_finished",
            run_id=run_id,
            agent="boss",
            ticket_id=ticket_id,
            action="run_ticket",
            stop_reason=stop_reason,
            error=error,
            duration_ms=duration,
            usage=usage_summary,
            result=decision.model_dump() if decision else None,
        )
        return RunRecord(
            run_id=run_id,
            ticket_id=ticket_id,
            ok=stop_reason == "completed",
            stop_reason=stop_reason,
            decision=decision,
            error=error,
            duration_ms=duration,
            requests=usage.requests,
            tool_calls=usage.tool_calls,
            total_tokens=usage.total_tokens,
            delegations=decision.consulted if decision else [],
        )


def _limits_detail() -> str:
    return (
        f"requests<={TICKET_LIMITS.request_limit}, "
        f"tool_calls<={TICKET_LIMITS.tool_calls_limit}, "
        f"tokens<={TICKET_LIMITS.total_tokens_limit}, "
        f"delegation_depth<={MAX_DELEGATION_DEPTH}"
    )


def _result_payload(result: Any) -> Any:
    """Pull something auditable out of an MCP tool result."""
    for attr in ("structured_content", "data", "content"):
        value = getattr(result, attr, None)
        if value is not None:
            return value
    return result
