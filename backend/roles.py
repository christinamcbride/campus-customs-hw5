"""The five roles, and which MCP tools each one is allowed to touch.

Scoping matters here. Every agent connects to the same MCP server, but an
agent that can see a tool will eventually call it, so the allowlists below are
what keep customer service out of the cash account and keep facilities from
placing stock orders.

One tool is on nobody's list: `decide_approval`. That is the human's tool, and
leaving it out of every role is the mechanism — not the prompt — that makes
"a human approves every payment" true. `assert_no_agent_can_approve()` checks
it, and the test suite calls that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

#: Never handed to an agent. The dashboard calls it on a person's behalf.
HUMAN_ONLY_TOOLS = frozenset({"decide_approval"})


@dataclass(frozen=True)
class Role:
    name: str
    title: str
    #: One line, used when another agent is choosing who to delegate to.
    blurb: str
    prompt_file: str
    tools: frozenset[str]
    #: Who this agent may delegate to. Every role lists the other four:
    #: the team is fully connected, as the assignment requires.
    peers: frozenset[str] = field(default_factory=frozenset)

    @property
    def prompt(self) -> str:
        path = PROMPTS_DIR / self.prompt_file
        if not path.exists():
            raise FileNotFoundError(f"Missing prompt file for {self.name}: {path}")
        return path.read_text(encoding="utf-8")


_ROLES = [
    Role(
        name="boss",
        title="Boss",
        blurb=(
            "Reads the ticket, decides who should work it, weighs competing "
            "claims on the shop's one cash account, and makes the final call."
        ),
        prompt_file="boss.md",
        tools=frozenset(
            {
                "get_ticket",
                "list_tickets",
                "update_ticket",
                "get_cash_balance",
                "list_approvals",
                "list_purchase_orders",
                "list_message_drafts",
            }
        ),
    ),
    Role(
        name="inventory",
        title="Inventory",
        blurb=(
            "Stock by SKU and size, shortfalls against what was asked for, "
            "which vendor can restock, lead times, and vendor holds."
        ),
        prompt_file="inventory.md",
        tools=frozenset(
            {
                "check_stock",
                "list_vendors",
                "list_invoices",
                "request_purchase_order_approval",
                "place_purchase_order",
                "list_purchase_orders",
                "list_approvals",
                "get_ticket",
            }
        ),
    ),
    Role(
        name="accounting",
        title="Accounting",
        blurb=(
            "Cash position, vendor invoices and how overdue they are, margins "
            "on a proposed price, and preparing payments for human approval."
        ),
        prompt_file="accounting.md",
        tools=frozenset(
            {
                "get_cash_balance",
                "list_invoices",
                "list_vendors",
                "check_discount_margin",
                "request_payment_approval",
                "record_payment",
                "list_approvals",
                "get_ticket",
            }
        ),
    ),
    Role(
        name="facilities",
        title="Facilities",
        blurb="The shop space — the Chapel Street lease, the landlord, and rent.",
        prompt_file="facilities.md",
        tools=frozenset(
            {
                "check_rent_due",
                "get_cash_balance",
                "request_payment_approval",
                "record_payment",
                "list_approvals",
                "get_ticket",
            }
        ),
    ),
    Role(
        name="customer_service",
        title="Customer Service",
        blurb=(
            "Drafts messages to the people who contacted the shop. Nothing is "
            "ever sent; drafts stay on the board for a person."
        ),
        prompt_file="customer_service.md",
        tools=frozenset(
            {
                "get_ticket",
                "check_stock",
                "list_purchase_orders",
                "draft_customer_message",
                "list_message_drafts",
            }
        ),
    ),
]

#: Full connectivity: every agent may delegate to every other agent.
ROLES: dict[str, Role] = {}
for _role in _ROLES:
    ROLES[_role.name] = Role(
        name=_role.name,
        title=_role.title,
        blurb=_role.blurb,
        prompt_file=_role.prompt_file,
        tools=_role.tools,
        peers=frozenset(r.name for r in _ROLES if r.name != _role.name),
    )

ROLE_NAMES = tuple(ROLES)


def assert_no_agent_can_approve() -> None:
    """Fail loudly if any role has been given a human-only tool."""
    for role in ROLES.values():
        leaked = role.tools & HUMAN_ONLY_TOOLS
        if leaked:
            raise AssertionError(
                f"Role {role.name!r} has been given human-only tool(s) "
                f"{sorted(leaked)}. Agents must never approve their own work."
            )


assert_no_agent_can_approve()
