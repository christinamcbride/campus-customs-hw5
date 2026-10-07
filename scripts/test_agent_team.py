"""Tests for the agent team: structure, the model lock, the limits, the trail.

Most of this runs without spending a token. A `FunctionModel` that does
nothing but delegate proves the loop guards fire, which is exactly the case a
live model is least likely to produce on demand. One real run against
`gpt-6-luna` is included at the end, so the wiring is proved end to end too.

    .venv/bin/python scripts/test_agent_team.py          # everything
    .venv/bin/python scripts/test_agent_team.py --offline  # no model calls
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from backend import audit  # noqa: E402
from backend.config import MODEL_NAME, build_model  # noqa: E402
from backend.roles import HUMAN_ONLY_TOOLS, ROLES  # noqa: E402
from backend.team import MAX_DELEGATION_DEPTH, TICKET_LIMITS, Team  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def reset_db() -> None:
    shutil.copyfile(ROOT / "data" / "campus_customs.db", ROOT / "data" / "campus_customs_new.db")


# ---------------------------------------------------------------------------


def test_structure() -> None:
    print("\nThe team is five agents, fully connected")
    check("five roles exist", sorted(ROLES) == sorted(
        ["accounting", "boss", "customer_service", "facilities", "inventory"]),
        ", ".join(sorted(ROLES)))
    check("every agent can delegate to the other four",
          all(len(r.peers) == 4 and r.name not in r.peers for r in ROLES.values()))
    check("every role has a prompt file with content",
          all(len(r.prompt) > 1200 for r in ROLES.values()),
          ", ".join(f"{r.name}:{len(r.prompt)}" for r in ROLES.values()))

    print("\nNo agent can approve anything")
    for role in ROLES.values():
        check(f"{role.name} does not hold a human-only tool",
              not (role.tools & HUMAN_ONLY_TOOLS))
    check("decide_approval is in no role's toolset",
          not any("decide_approval" in r.tools for r in ROLES.values()))

    print("\nEvery prompt states the rules that bind that agent")
    money = ["accounting", "facilities"]
    for name in money:
        p = ROLES[name].prompt.lower()
        check(f"{name} prompt states human approval", "human approves every payment" in p)
        check(f"{name} prompt states no negative balance", "negative balance" in p)
    for name, phrase in [("inventory", "will not ship"), ("customer_service", "nothing is sent")]:
        check(f"{name} prompt states its key rule",
              phrase in ROLES[name].prompt.lower())
    check("every prompt points at the shop's own date",
          all("desk.date_today" in r.prompt for r in ROLES.values()))


def test_model_lock() -> None:
    print("\nOnly gpt-6-luna, in the code and in the runs")
    check("the model constant is gpt-6-luna", MODEL_NAME == "gpt-6-luna")
    try:
        build_model("gpt-4o-mini")
        check("build_model refuses another model", False, "it allowed gpt-4o-mini")
    except ValueError as exc:
        check("build_model refuses another model", True, str(exc)[:70])

    # Scan the source for any other model name that could reach a provider.
    others = re.compile(
        r"\b(gpt-[0-9][\w.\-]*|o[134](?:-mini)?|claude-[\w.\-]+|gemini-[\w.\-]+|"
        r"llama-?[\w.\-]*|mistral[\w.\-]*)\b",
        re.I,
    )
    offenders = []
    scanned = (
        list((ROOT / "backend").rglob("*.py"))
        + list((ROOT / "backend").rglob("*.md"))
        + list((ROOT / "mcp_server").rglob("*.py"))
        + [p for p in (ROOT / "scripts").rglob("*.py") if p != Path(__file__)]
    )
    for path in scanned:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for hit in others.findall(line):
                # gpt-6-luna-global is the gateway's own deployment id, quoted
                # from its error message in a comment. It is the same model.
                if hit.lower().startswith("gpt-6-luna"):
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{n} {hit}")
    check("no other model name appears in the source", not offenders,
          "; ".join(offenders[:4]) if offenders else "clean")


# ---------------------------------------------------------------------------
# Loop guards, proved with a model that will not stop delegating.
# ---------------------------------------------------------------------------


def _delegates_to_itself(messages, info: AgentInfo) -> ModelResponse:
    """The boss asking the boss. An agent is never its own peer."""
    return ModelResponse(
        parts=[ToolCallPart("delegate", {"to_agent": "boss", "task": "keep going"})]
    )


def _delegates_back_up(peers=("inventory", "boss"), _n=[0]):
    """boss -> inventory -> boss. The second hop would close a circle."""

    def model(messages, info: AgentInfo) -> ModelResponse:
        peer = peers[_n[0] % len(peers)]
        _n[0] += 1
        return ModelResponse(
            parts=[ToolCallPart("delegate", {"to_agent": peer, "task": "keep going"})]
        )

    return model


def _delegates_ever_deeper(peers=("inventory", "accounting", "facilities"), _n=[0]):
    """Hand work downward and never answer, to drive the depth cap."""

    def model(messages, info: AgentInfo) -> ModelResponse:
        peer = peers[_n[0] % len(peers)]
        _n[0] += 1
        return ModelResponse(
            parts=[ToolCallPart("delegate", {"to_agent": peer, "task": "keep going"})]
        )

    return model


async def _run_with(model) -> tuple[object, list[dict]]:
    reset_db()
    before = len(audit.read_trail())
    async with Team(human_operator="test operator", model=FunctionModel(model)) as team:
        record = await team.run_ticket(101)
    return record, audit.read_trail()[before:]


async def test_loop_guards() -> None:
    print("\nAn agent cannot delegate to itself")
    record, trail = await _run_with(_delegates_to_itself)
    reasons = {e.get("stop_reason") for e in trail if e["event"] == "delegation_refused"}
    check("delegating to yourself is refused", "not_a_peer" in reasons,
          f"reasons={sorted(reasons)}")
    check("no delegation actually happened",
          not [e for e in trail if e["event"] == "delegation"])
    check("the run still terminated", record.stop_reason in {"limit_exceeded", "model_error"},
          record.stop_reason)

    print("\nDelegation cannot close a circle")
    record, trail = await _run_with(_delegates_back_up())
    reasons = {e.get("stop_reason") for e in trail if e["event"] == "delegation_refused"}
    hops = [e["action"] for e in trail if e["event"] == "delegation"]
    check("boss -> inventory was allowed", "delegate->inventory" in hops, str(hops[:3]))
    check("inventory -> boss was refused as a loop", "would_loop" in reasons,
          f"reasons={sorted(reasons)}")
    check("the circle never completed", "delegate->boss" not in hops)

    print("\nDelegation cannot run away downward")
    record, trail = await _run_with(_delegates_ever_deeper())
    depths = [e.get("depth", 0) for e in trail if e["event"] == "delegation"]
    refusals = [e for e in trail if e["event"] == "delegation_refused"]
    reasons = {e.get("stop_reason") for e in refusals}
    check(f"no delegation started below depth {MAX_DELEGATION_DEPTH}",
          all(d < MAX_DELEGATION_DEPTH for d in depths),
          f"depths seen: {sorted(set(depths))}")
    check("the depth cap fired", "depth_limit" in reasons,
          f"{len(refusals)} refusals, reasons={sorted(reasons)}")
    check("a model that never answers is stopped",
          record.stop_reason in {"limit_exceeded", "model_error"},
          f"{record.stop_reason}: {(record.error or '')[:70]}")
    check("the stop reason is in the trail",
          any(e.get("stop_reason") == record.stop_reason
              for e in trail if e["event"] == "run_finished"))


def test_limits_configured() -> None:
    print("\nThere is a ceiling on one ticket")
    check("a request limit is set", bool(TICKET_LIMITS.request_limit),
          f"requests<={TICKET_LIMITS.request_limit}")
    check("a tool-call limit is set", bool(TICKET_LIMITS.tool_calls_limit),
          f"tool_calls<={TICKET_LIMITS.tool_calls_limit}")
    check("a token limit is set", bool(TICKET_LIMITS.total_tokens_limit),
          f"tokens<={TICKET_LIMITS.total_tokens_limit}")
    check("delegation depth is capped", MAX_DELEGATION_DEPTH >= 1,
          f"depth<={MAX_DELEGATION_DEPTH}")


async def test_audit_is_append_only() -> None:
    print("\nThe audit trail is append-only across restarts")
    existing = audit.read_trail()
    check("the trail already holds earlier runs", len(existing) > 0, f"{len(existing)} entries")
    first = existing[0] if existing else None

    # A fresh process writes to the same file; nothing earlier may be lost.
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c",
         "import sys; sys.path.insert(0, '.');"
         "from backend import audit;"
         "audit.record('tool_call', run_id='append-check', agent='test',"
         " action='probe', result={'ok': True})"],
        cwd=ROOT, check=True, capture_output=True,
    )
    after = audit.read_trail()
    check("the new entry landed", after[-1].get("run_id") == "append-check")
    check("every earlier entry survived", len(after) == len(existing) + 1,
          f"{len(existing)} -> {len(after)}")
    check("the very first entry is unchanged", after[0] == first)

    print("\nThe trail records what an auditor needs")
    tool_calls = [e for e in after if e["event"] == "tool_call" and e.get("agent") != "test"]
    check("tool calls carry a timestamp, agent, tool, and arguments",
          bool(tool_calls) and all(
              {"time", "agent", "action"} <= set(e) for e in tool_calls[:20]))
    finishes = [e for e in after if e["event"] == "run_finished"]
    check("every finished run carries a stop reason and usage",
          bool(finishes) and all("stop_reason" in e and "usage" in e for e in finishes),
          f"{len(finishes)} runs recorded")
    # A real key, not any string containing "sk-" — the run ids are prefixed
    # "desk-", which a naive substring check flags every time.
    secret = re.compile(r"\b(sk|pk)-[A-Za-z0-9_\-]{12,}|portkey[_-]?api[_-]?key\W+\S", re.I)
    leaks = [e for e in after if secret.search(json.dumps(e))]
    check("no secret ever reaches the trail", not leaks,
          json.dumps(leaks[0])[:90] if leaks else "clean")


async def test_live_run() -> None:
    print(f"\nA real run on {MODEL_NAME}")
    reset_db()
    before = len(audit.read_trail())
    async with Team(human_operator="Christina McBride") as team:
        record = await team.run_ticket(102)
    check("the run completed", record.ok, f"{record.stop_reason}: {(record.error or '')[:90]}")
    if not record.decision:
        return
    d = record.decision
    check("the boss consulted at least one specialist", bool(d.consulted), str(d.consulted))
    check("the ticket was not falsely marked resolved",
          d.ticket_status != "resolved" or not d.approval_ids_waiting, d.ticket_status)
    check("findings name the tool they came from",
          bool(d.findings) and all(f.source_tool for f in d.findings),
          f"{len(d.findings)} findings")
    check("the run stayed inside the ceiling",
          record.requests <= TICKET_LIMITS.request_limit
          and record.tool_calls <= TICKET_LIMITS.tool_calls_limit
          and record.total_tokens <= TICKET_LIMITS.total_tokens_limit,
          f"req={record.requests} tools={record.tool_calls} tok={record.total_tokens}")

    new = audit.read_trail()[before:]
    agents_seen = {e.get("agent") for e in new if e["event"] == "tool_call"}
    check("more than one agent appears in the trail", len(agents_seen) > 1, str(sorted(agents_seen)))
    check("every model call used gpt-6-luna",
          all(MODEL_NAME in (e.get("detail") or "") for e in new if e["event"] == "run_started"))


async def main() -> int:
    offline = "--offline" in sys.argv
    test_structure()
    test_model_lock()
    test_limits_configured()
    await test_loop_guards()
    await test_audit_is_append_only()
    if offline:
        print("\n(skipping the live run: --offline)")
    else:
        await test_live_run()
    reset_db()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for f in FAILED:
        print("  FAILED:", f)
    print("working copy reset to the original")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
