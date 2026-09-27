"""Shared base for pool entities."""

from __future__ import annotations

import logging

from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .pool import AIPool, AIPoolConfigEntry

_LOGGER = logging.getLogger(__name__)


def pool_device_info(pool: AIPool, entry: AIPoolConfigEntry) -> DeviceInfo:
    """Device every entity of one pool hangs off.

    Shared so the pool entity and its diagnostic sensors cannot disagree about
    the device they describe: the sensors used to build their own copy without
    manufacturer or model.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="AI Pool",
        model=f"{pool.pool_type} pool",
        entry_type=DeviceEntryType.SERVICE,
    )


class AIPoolEntity(Entity):
    """Common identity, device grouping and availability for every pool entity.

    Named after its device: the pool is the device's only primary entity, so
    the ai_task, conversation and stt platforms set ``name = None`` and the
    friendly name is the pool's title. The tts platform sets a translation key
    instead, because the tts manager reads ``entity.name`` directly and refuses
    an engine whose name is None. Not set here: ``Entity.name`` returns
    ``_attr_name`` whenever the attribute exists, even as None, which would
    shadow the tts translation key.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, pool: AIPool, entry: AIPoolConfigEntry) -> None:
        """Initialise identity from the config entry."""
        self.pool = pool
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = pool_device_info(pool, entry)
        self._was_available: bool | None = None

    @property
    def available(self) -> bool:
        """Available while at least one member could still answer.

        Exhausted or cooling members keep the pool available: they are tried
        as last resort, and a call that fails loudly beats one that never
        runs. A pool with no reachable member at all cannot serve, and says so.
        """
        return self.pool.can_serve()

    async def async_added_to_hass(self) -> None:
        """Follow member availability, which changes without the pool."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [member.entity_id for member in self.pool.members],
                self._handle_member_change,
            )
        )
        # Disabling a member on an auth failure happens inside the pool.
        self.async_on_remove(self.pool.async_add_listener(self._handle_pool_change))
        self._log_availability()

    @callback
    def _handle_member_change(self, event: Event[EventStateChangedData]) -> None:
        """Re-evaluate availability when a member's state changes."""
        self._handle_pool_change()

    @callback
    def _handle_pool_change(self) -> None:
        """Write state only when availability actually flipped."""
        if self._log_availability():
            self.async_write_ha_state()

    @callback
    def _log_availability(self) -> bool:
        """Log once on each availability change; return whether it changed."""
        available = self.available
        previous, self._was_available = self._was_available, available
        if previous is None:
            if not available:
                _LOGGER.info(
                    "Pool %s has no reachable member and is unavailable",
                    self._entry.title,
                )
            return False
        if previous == available:
            return False
        if available:
            _LOGGER.info("Pool %s is available again", self._entry.title)
        else:
            _LOGGER.info(
                "Pool %s has no reachable member and is unavailable",
                self._entry.title,
            )
        return True
