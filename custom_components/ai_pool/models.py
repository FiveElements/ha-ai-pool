"""Resolve which provider model sits behind a member entity.

Two members on the same model are a pool when they are two accounts: that is
the quota split this integration exists to provide. They are a duplicate when
they share a provider config entry - one API key listed twice.

A capacity refusal is this key's view of the model, not every other key's,
so a failover still tries the next account. It only skips other members of
the same account on that model. The repair is the same shape: it only fires
for the same-account case.

Nothing in Home Assistant exposes "the model behind this entity", so this reads
the member's own config entry. Providers name that option differently and are
free to change it, which makes this a heuristic and not a lookup: an unknown
model or account is reported as ``None`` and simply carries no conclusion.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

# Ordered by how specific they are. "chat_model" is what the Google and OpenAI
# conversation entities store; "model" is the more common spelling elsewhere.
MODEL_KEYS = ("chat_model", "model", "model_name")


@callback
def member_config_entry_id(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return the provider config entry that owns this member, if known.

    Two entities on the same config entry share an API key. Two entities on
    different entries are two accounts.
    """
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is None:
        return None
    return registry_entry.config_entry_id


@callback
def member_model(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return the model configured for a member, or None if it cannot be read.

    A member's model may live on its config entry or, for providers that
    publish several entities from one account, on the subentry that created
    that particular entity. The subentry is checked first because it is the
    more specific of the two.
    """
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is None or registry_entry.config_entry_id is None:
        return None

    config_entry = hass.config_entries.async_get_entry(registry_entry.config_entry_id)
    if config_entry is None:
        return None

    sources: list[Mapping[str, Any]] = []
    subentry_id = getattr(registry_entry, "config_subentry_id", None)
    if subentry_id and (subentry := config_entry.subentries.get(subentry_id)):
        sources.append(subentry.data)
    sources.append({**config_entry.data, **config_entry.options})

    for source in sources:
        for key in MODEL_KEYS:
            if value := source.get(key):
                return str(value)
    return None


@callback
def shared_models(models: Mapping[str, str | None]) -> dict[str, list[str]]:
    """Group members by model, keeping only the models used more than once.

    Members whose model could not be read are left out rather than lumped
    together: "unknown" is not evidence that two members match.
    """
    by_model: dict[str, list[str]] = {}
    for entity_id, model in models.items():
        if not model:
            continue
        by_model.setdefault(model, []).append(entity_id)
    return {model: members for model, members in by_model.items() if len(members) > 1}


@callback
def shared_account_models(
    models: Mapping[str, str | None],
    accounts: Mapping[str, str | None],
) -> dict[str, list[str]]:
    """Members that share a model *and* a provider config entry.

    Two accounts on the same model is quota rotation. Two entities on one
    account and one model are the same membership listed twice. Unreadable
    accounts, like unreadable models, conclude nothing.
    """
    by_key: dict[tuple[str, str], list[str]] = {}
    for entity_id, model in models.items():
        account = accounts.get(entity_id)
        if not model or not account:
            continue
        by_key.setdefault((account, model), []).append(entity_id)

    duplicates: dict[str, list[str]] = {}
    for (_account, model), members in by_key.items():
        if len(members) > 1:
            duplicates.setdefault(model, []).extend(members)
    return duplicates
