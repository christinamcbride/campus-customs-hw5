"""The audit trail.

Every step the agent team takes is appended to `output/audit_trail.json` as
one JSON object per line. Append-only: the file is never rewritten, never
truncated, and survives restarts, so a run can be reconstructed afterwards
from the file alone.

JSON Lines rather than one big JSON array, for two reasons. A crashed run
still leaves valid, readable records instead of a truncated array that no
parser will touch. And appending a line is atomic enough to be safe without
rewriting everything that came before.

What is recorded: the time, which agent acted, what it did, the arguments it
used, a short summary of what came back, and why a run stopped. What is not
recorded: API keys, and customer contact details beyond the requester name
already printed on the public ticket.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_PATH = Path(__file__).resolve().parents[1] / "output" / "audit_trail.json"

_LOCK = threading.Lock()
log = logging.getLogger("campus_customs.audit")

#: Values longer than this are truncated. The trail is for auditing what
#: happened, not for storing a second copy of the database.
MAX_VALUE_CHARS = 240

#: Argument names whose values are never written out, at any nesting depth.
REDACT_KEYS = {
    "api_key",
    "portkey_api_key",
    "authorization",
    "token",
    "secret",
    "password",
    "cookie",
    "email",
    "phone",
    "address",
}


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + f"... [{len(value)} chars]"
    return value


def scrub(value: Any, depth: int = 0) -> Any:
    """Drop secrets and personal contact details, and shorten long values."""
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in REDACT_KEYS else scrub(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        shown = [scrub(v, depth + 1) for v in list(value)[:10]]
        if len(value) > 10:
            shown.append(f"... {len(value) - 10} more")
        return shown
    return _clip(value)


def summarise(value: Any) -> Any:
    """A compact stand-in for a tool result.

    Long lists become a count plus the first couple of entries. The trail
    should say what a tool returned, not duplicate it.
    """
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, dict):
        return scrub(value)
    if isinstance(value, (list, tuple)):
        items = list(value)
        return {
            "count": len(items),
            "first": [scrub(i) for i in items[:2]],
        }
    return _clip(str(value))


def _append(entry: dict[str, Any]) -> None:
    """Append one record. A failure here must never break a run."""
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _LOCK:
            with AUDIT_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        log.exception("Could not append to the audit trail")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(
    event: str,
    *,
    run_id: str,
    agent: str | None = None,
    ticket_id: int | None = None,
    action: str | None = None,
    arguments: Any = None,
    result: Any = None,
    stop_reason: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    depth: int | None = None,
    usage: dict[str, Any] | None = None,
    detail: str | None = None,
) -> None:
    """Append one step of the agent loop.

    `event` is the shape of the record — `run_started`, `agent_started`,
    `tool_call`, `delegation`, `agent_finished`, `run_finished`. Fields that
    do not apply are left out rather than written as null.
    """
    entry: dict[str, Any] = {"time": _now(), "event": event, "run_id": run_id}
    optional = {
        "agent": agent,
        "ticket_id": ticket_id,
        "action": action,
        "arguments": scrub(arguments) if arguments is not None else None,
        "result": summarise(result) if result is not None else None,
        "stop_reason": stop_reason,
        "error": error,
        "duration_ms": duration_ms,
        "depth": depth,
        "usage": usage,
        "detail": _clip(detail) if detail else None,
    }
    entry.update({k: v for k, v in optional.items() if v is not None})
    _append(entry)


def read_trail(limit: int | None = None) -> list[dict[str, Any]]:
    """Read the trail back. Malformed lines are skipped, not fatal."""
    if not AUDIT_PATH.exists():
        return []
    entries = []
    with AUDIT_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-limit:] if limit else entries
