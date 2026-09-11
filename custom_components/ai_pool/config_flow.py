"""Config and options flow for AI Pool."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_COOLDOWN,
    CONF_DAILY_LIMIT,
    CONF_MAX_ATTEMPTS,
    CONF_MEMBERS,
    CONF_POOL_TYPE,
    CONF_RPM_LIMIT,
    CONF_STRATEGY,
    CONF_STT_BUFFER_LIMIT,
    CONF_TIMEOUT,
    CONF_WEIGHT,
    CONFIG_VERSION,
    DEFAULT_COOLDOWN,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_STRATEGY,
    DEFAULT_STT_BUFFER_LIMIT,
    DEFAULT_TIMEOUT,
    DEFAULT_WEIGHT,
    DOMAIN,
    POOL_TYPE_STT,
    POOL_TYPES,
    STRATEGIES,
)

LIMIT_PREFIX = "limit_"
RPM_PREFIX = "rpm_"
WEIGHT_PREFIX = "weight_"
# The form shows megabytes; storage and the STT entity keep bytes, which is
# what the clip comparison actually measures.
_BYTES_PER_MB = 1024 * 1024


def _own_entities(hass: HomeAssistant) -> set[str]:
    """Entity ids published by this integration.

    Excluded from member pickers so a pool can never contain itself, which
    would recurse until the stack gives out.
    """
    registry = er.async_get(hass)
    return {
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
    }


def _stt_buffer_mb(raw: Any) -> int:
    """Convert a stored byte limit into the megabytes the form shows."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_STT_BUFFER_LIMIT
    return max(1, value // _BYTES_PER_MB)


def _policy_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Routing policy fields shared by the create and options flows."""
    policy = {
        CONF_STRATEGY: user_input[CONF_STRATEGY],
        CONF_COOLDOWN: int(user_input[CONF_COOLDOWN]),
        CONF_MAX_ATTEMPTS: int(user_input[CONF_MAX_ATTEMPTS]),
        CONF_TIMEOUT: int(user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
    }
    if CONF_STT_BUFFER_LIMIT in user_input:
        policy[CONF_STT_BUFFER_LIMIT] = (
            int(user_input[CONF_STT_BUFFER_LIMIT]) * _BYTES_PER_MB
        )
    return policy


def _members_schema(
    hass: HomeAssistant,
    pool_type: str,
    defaults: dict[str, Any],
) -> vol.Schema:
    """Build the schema for picking members and the routing policy."""
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_MEMBERS, default=defaults.get(CONF_MEMBERS, [])
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=pool_type,
                multiple=True,
                exclude_entities=sorted(_own_entities(hass)),
            )
        ),
        vol.Required(
            CONF_STRATEGY, default=defaults.get(CONF_STRATEGY, DEFAULT_STRATEGY)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(STRATEGIES),
                translation_key="strategy",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_COOLDOWN, default=defaults.get(CONF_COOLDOWN, DEFAULT_COOLDOWN)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=86400,
                step=30,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_MAX_ATTEMPTS,
            default=defaults.get(CONF_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_TIMEOUT,
            default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=900,
                step=5,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
    if pool_type == POOL_TYPE_STT:
        fields[
            vol.Required(
                CONF_STT_BUFFER_LIMIT,
                default=_stt_buffer_mb(
                    defaults.get(CONF_STT_BUFFER_LIMIT, DEFAULT_STT_BUFFER_LIMIT)
                ),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=64,
                step=1,
                unit_of_measurement="MB",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
    return vol.Schema(fields)


def _limits_schema(member_ids: list[str], existing: list[dict[str, Any]]) -> vol.Schema:
    """Build the schema for the per-member allowances and weight.

    Three numbers per member: requests per day, requests per minute, and the
    routing weight. Providers meter tokens too, but Home Assistant never
    reports a token count back, so there is nothing to declare against.
    """
    previous = {item["entity_id"]: item for item in existing}
    fields: dict[Any, Any] = {}
    for member_id in member_ids:
        old = previous.get(member_id, {})
        fields[
            vol.Required(
                f"{LIMIT_PREFIX}{member_id}",
                default=old.get(CONF_DAILY_LIMIT, 0),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=1000000,
                step=1,
                unit_of_measurement="req/day",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
        fields[
            vol.Required(
                f"{RPM_PREFIX}{member_id}",
                default=old.get(CONF_RPM_LIMIT, 0),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=100000,
                step=1,
                unit_of_measurement="req/min",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
        fields[
            vol.Required(
                f"{WEIGHT_PREFIX}{member_id}",
                default=old.get(CONF_WEIGHT, DEFAULT_WEIGHT),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=100, step=1, mode=selector.NumberSelectorMode.BOX
            )
        )
    return vol.Schema(fields)


def _pool_key(pool_type: str, member_ids: list[str]) -> str:
    """Identity of a pool: what it fronts, and for whom.

    Two pools over the same members each keep their own counters and each
    believe they hold the whole allowance, which is the double spend this
    integration exists to prevent. Order is not part of the identity - the
    same members in a different preference order are still the same members.
    """
    return f"{pool_type}:" + ",".join(sorted(member_ids))


def _build_members(
    member_ids: list[str], user_input: dict[str, Any]
) -> list[dict[str, Any]]:
    """Assemble member records from the limits step input."""
    return [
        {
            "entity_id": member_id,
            CONF_DAILY_LIMIT: int(user_input.get(f"{LIMIT_PREFIX}{member_id}", 0) or 0),
            CONF_RPM_LIMIT: int(user_input.get(f"{RPM_PREFIX}{member_id}", 0) or 0),
            CONF_WEIGHT: int(
                user_input.get(f"{WEIGHT_PREFIX}{member_id}", DEFAULT_WEIGHT) or 1
            ),
        }
        for member_id in member_ids
    ]


class AIPoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a pool."""

    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        """Start with an empty draft."""
        self._draft: dict[str, Any] = {}
        self._member_ids: list[str] = []
        self._existing_members: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the pool and choose which domain it fronts."""
        if user_input is not None:
            self._draft = dict(user_input)
            return await self.async_step_members()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_POOL_TYPE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(POOL_TYPES),
                        translation_key="pool_type",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit members and policy of an existing pool without removing it.

        Pool type stays: it decides which platform is loaded. Members,
        strategy and allowances are the same fields as the options flow,
        reached from Reconfigure on the entry rather than Configure.
        """
        del user_input
        entry = self._get_reconfigure_entry()
        current = {**entry.data, **entry.options}
        self._existing_members = list(current.get(CONF_MEMBERS, []))
        self._draft = {
            CONF_NAME: entry.title,
            CONF_POOL_TYPE: current[CONF_POOL_TYPE],
            CONF_STRATEGY: current.get(CONF_STRATEGY, DEFAULT_STRATEGY),
            CONF_COOLDOWN: current.get(CONF_COOLDOWN, DEFAULT_COOLDOWN),
            CONF_MAX_ATTEMPTS: current.get(CONF_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS),
            CONF_TIMEOUT: current.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            CONF_MEMBERS: [item["entity_id"] for item in self._existing_members],
        }
        if CONF_STT_BUFFER_LIMIT in current:
            self._draft[CONF_STT_BUFFER_LIMIT] = current[CONF_STT_BUFFER_LIMIT]
        return await self.async_step_members()

    async def async_step_members(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick members and the routing policy."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._member_ids = list(user_input[CONF_MEMBERS])
            if not self._member_ids:
                errors[CONF_MEMBERS] = "no_members"
            else:
                self._draft.update(_policy_from_input(user_input))
                return await self.async_step_limits()

        return self.async_show_form(
            step_id="members",
            data_schema=_members_schema(
                self.hass, self._draft[CONF_POOL_TYPE], self._draft
            ),
            errors=errors,
        )

    async def async_step_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Declare each member's daily allowance and weight."""
        if user_input is not None:
            data = dict(self._draft)
            data[CONF_MEMBERS] = _build_members(self._member_ids, user_input)
            title = data.pop(CONF_NAME)
            key = _pool_key(data[CONF_POOL_TYPE], self._member_ids)
            if self.source == SOURCE_RECONFIGURE:
                entry = self._get_reconfigure_entry()
                clash = next(
                    (
                        other
                        for other in self.hass.config_entries.async_entries(DOMAIN)
                        if other.unique_id == key and other.entry_id != entry.entry_id
                    ),
                    None,
                )
                if clash is not None:
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    data=data,
                    options={},
                    unique_id=key,
                )
            await self.async_set_unique_id(key)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=data)

        existing = self._existing_members if self.source == SOURCE_RECONFIGURE else []
        return self.async_show_form(
            step_id="limits",
            data_schema=_limits_schema(self._member_ids, existing),
            description_placeholders={"members": ", ".join(self._member_ids)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> AIPoolOptionsFlow:
        """Return the options flow."""
        return AIPoolOptionsFlow()


class AIPoolOptionsFlow(OptionsFlow):
    """Edit members and policy of an existing pool.

    The pool type is intentionally not editable: it decides which platform is
    loaded, so changing it would orphan the published entity.
    """

    def __init__(self) -> None:
        """Start with an empty draft."""
        self._draft: dict[str, Any] = {}
        self._member_ids: list[str] = []

    @property
    def _current(self) -> dict[str, Any]:
        """Effective current configuration."""
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick members and the routing policy."""
        errors: dict[str, str] = {}
        current = self._current

        if user_input is not None:
            self._member_ids = list(user_input[CONF_MEMBERS])
            if not self._member_ids:
                errors[CONF_MEMBERS] = "no_members"
            else:
                self._draft = {
                    CONF_POOL_TYPE: current[CONF_POOL_TYPE],
                    **_policy_from_input(user_input),
                }
                return await self.async_step_limits()

        defaults = dict(current)
        defaults[CONF_MEMBERS] = [
            item["entity_id"] for item in current.get(CONF_MEMBERS, [])
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=_members_schema(self.hass, current[CONF_POOL_TYPE], defaults),
            errors=errors,
        )

    async def async_step_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Declare each member's daily allowance and weight."""
        if user_input is not None:
            data = dict(self._draft)
            data[CONF_MEMBERS] = _build_members(self._member_ids, user_input)
            # The member set may have changed, so the pool's identity may now
            # collide with another pool's.
            key = _pool_key(data[CONF_POOL_TYPE], self._member_ids)
            clash = next(
                (
                    entry
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                    if entry.unique_id == key
                    and entry.entry_id != self.config_entry.entry_id
                ),
                None,
            )
            if clash is not None:
                return self.async_show_form(
                    step_id="limits",
                    data_schema=_limits_schema(
                        self._member_ids, self._draft.get(CONF_MEMBERS, [])
                    ),
                    errors={"base": "duplicate_members"},
                    description_placeholders={"members": ", ".join(self._member_ids)},
                )
            # Written back into `data`, not left in `options`. An options flow
            # normally stores its result in `options`, which would leave two
            # copies of the same configuration - `data` frozen at creation and
            # `options` current - and every reader merging the two. One copy
            # means a future migration has one place to fix.
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=data, options={}, unique_id=key
            )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="limits",
            data_schema=_limits_schema(
                self._member_ids, self._current.get(CONF_MEMBERS, [])
            ),
            description_placeholders={"members": ", ".join(self._member_ids)},
        )
