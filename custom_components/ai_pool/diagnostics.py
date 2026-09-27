"""Diagnostics support for AI Pool."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from .pool import AIPool, AIPoolConfigEntry


def _redact_error(value: Any) -> Any:
    """Keep the failure kind of a stored error, drop the provider's text.

    The pool stores no credentials, but ``last_error`` is whatever the
    provider said, and some echo the request back - Google's REST errors can
    carry the URL with ``?key=`` in it. Diagnostics get pasted into public
    issues, so only the classified kind survives, which is what explains a
    routing decision anyway.
    """
    if not isinstance(value, str):
        return value
    kind, separator, _ = value.partition(":")
    return f"{kind}: {REDACTED}" if separator else REDACTED


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AIPoolConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The configuration needs no redaction: it references member entities,
    whose own integrations hold the keys. Provider error text does.
    """
    pool: AIPool = entry.runtime_data
    members = []
    for view in pool.snapshot():
        row = view.as_dict()
        row["last_error"] = _redact_error(row.get("last_error"))
        members.append(row)
    return {
        "config": {**entry.data, **entry.options},
        "strategy": pool.strategy,
        "max_attempts": pool.max_attempts,
        "cooldown_seconds": pool.cooldown.total_seconds(),
        "cursor": pool.store.state.cursor,
        "members": members,
    }
