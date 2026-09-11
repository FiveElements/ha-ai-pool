"""Integration setup and teardown."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ai_pool import async_migrate_entry
from custom_components.ai_pool.binary_sensor import SCAN_INTERVAL
from custom_components.ai_pool.config_flow import _pool_key
from custom_components.ai_pool.const import (
    ATTR_POOL,
    CONF_COOLDOWN,
    CONF_DAILY_LIMIT,
    CONF_MAX_ATTEMPTS,
    CONF_MEMBERS,
    CONF_POOL_TYPE,
    CONF_STRATEGY,
    CONF_WEIGHT,
    CONFIG_VERSION,
    DOMAIN,
    SERVICE_RESET_MEMBER,
    STRATEGY_ROUND_ROBIN,
)

A = "member_a"
B = "member_b"


def test_problem_sensor_polls_once_a_minute() -> None:
    """Member availability can change without the pool, so this one polls."""
    assert SCAN_INTERVAL.total_seconds() == 60


def build_entry(pool_type: str) -> MockConfigEntry:
    """Create a config entry for a pool of the given type."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"{pool_type} pool",
        data={
            CONF_POOL_TYPE: pool_type,
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [
                {
                    "entity_id": f"{pool_type}.{name}",
                    CONF_DAILY_LIMIT: 100,
                    CONF_WEIGHT: 1,
                }
                for name in (A, B)
            ],
        },
    )


@pytest.fixture(autouse=True)
async def setup_core(hass: HomeAssistant) -> None:
    """Set up the core integration the fronted domains rely on.

    conversation reads the exposed-entity registry owned by the homeassistant
    component, which a real instance always has and a test one does not.
    """
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.mark.parametrize("pool_type", ["ai_task", "conversation", "tts", "stt"])
async def test_setup_and_unload(hass: HomeAssistant, pool_type: str) -> None:
    """Every pool type loads its own platform plus the sensors."""
    assert await async_setup_component(hass, pool_type, {})

    entry = build_entry(pool_type)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # Calls and latency per member, plus the pool's own fallback-rate sensor.
    # Latency is registered but disabled by default (noisy measurements).
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    sensors = [entity for entity in entities if entity.domain == "sensor"]
    assert len(sensors) == 5
    # Distinct ids prove the name translations resolved: without them every
    # sensor would fall back to the device name and collide.
    assert len({entity.entity_id for entity in sensors}) == 5

    # One problem sensor per pool, whatever the member count.
    problems = [entity for entity in entities if entity.domain == "binary_sensor"]
    assert len(problems) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_pool_entity_is_published(hass: HomeAssistant) -> None:
    """The pool must appear as a normal entity in its target domain."""
    assert await async_setup_component(hass, "ai_task", {})

    entry = build_entry("ai_task")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    pool_entities = [
        state
        for state in hass.states.async_all("ai_task")
        if state.attributes.get("friendly_name") == "ai_task pool"
    ]
    assert len(pool_entities) == 1


async def test_options_update_triggers_reload(hass: HomeAssistant) -> None:
    """Editing members must take effect without a restart."""
    assert await async_setup_component(hass, "ai_task", {})

    entry = build_entry("ai_task")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 60,
            CONF_MAX_ATTEMPTS: 1,
            CONF_MEMBERS: [
                {
                    "entity_id": "ai_task.member_a",
                    CONF_DAILY_LIMIT: 5,
                    CONF_WEIGHT: 1,
                }
            ],
        },
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.runtime_data.members) == 1
    assert entry.runtime_data.max_attempts == 1


async def test_setup_removes_sensors_for_members_that_left(
    hass: HomeAssistant,
) -> None:
    """A departed member used to leave unavailable sensors in the registry."""
    assert await async_setup_component(hass, "ai_task", {})

    entry = build_entry("ai_task")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    orphan = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_ai_task.retired",
        config_entry=entry,
        suggested_object_id="retired_calls",
    )
    orphan_id = orphan.entity_id

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(orphan_id) is None


async def test_dropping_a_member_prunes_its_sensors(hass: HomeAssistant) -> None:
    """Reload is what actually removes the leftover registry rows."""
    assert await async_setup_component(hass, "ai_task", {})

    entry = build_entry("ai_task")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    retired = f"{entry.entry_id}_ai_task.member_b"
    registry = er.async_get(hass)
    assert any(
        item.unique_id == retired
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    )

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [
                {
                    "entity_id": "ai_task.member_a",
                    CONF_DAILY_LIMIT: 100,
                    CONF_WEIGHT: 1,
                }
            ],
        },
    )
    await hass.async_block_till_done()

    leftover = [
        item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if "member_b" in item.unique_id
    ]
    assert leftover == []


async def test_reset_member_rejects_an_unknown_pool(hass: HomeAssistant) -> None:
    """The service must not guess at a pool that is not in the registry."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "ai_task", {})
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(ServiceValidationError, match=r"pool_not_found|No AI Pool"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RESET_MEMBER,
            {ATTR_POOL: "missing-entry"},
            blocking=True,
        )


async def test_reset_member_rejects_an_unloaded_pool(hass: HomeAssistant) -> None:
    """An unloaded entry still exists, but it has nothing to reset."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "ai_task", {})

    entry = build_entry("ai_task")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match=r"pool_not_loaded|not loaded"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RESET_MEMBER,
            {ATTR_POOL: entry.entry_id},
            blocking=True,
        )


async def test_migrate_stamps_unique_id_from_the_member_set(
    hass: HomeAssistant,
) -> None:
    """Version 1 entries restored without unique_id used to collide silently."""
    assert await async_setup_component(hass, "ai_task", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ai_task pool",
        version=1,
        unique_id=None,
        data=build_entry("ai_task").data,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == CONFIG_VERSION
    assert entry.unique_id == _pool_key(
        "ai_task", ["ai_task.member_a", "ai_task.member_b"]
    )


async def test_migrate_does_not_steal_a_unique_id_already_taken(
    hass: HomeAssistant,
) -> None:
    """Two restored v1 clones must not be given the same unique_id."""
    key = _pool_key("ai_task", ["ai_task.member_a", "ai_task.member_b"])
    first = MockConfigEntry(
        domain=DOMAIN,
        title="First",
        version=2,
        unique_id=key,
        data=build_entry("ai_task").data,
    )
    first.add_to_hass(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        version=1,
        unique_id=None,
        data=build_entry("ai_task").data,
    )
    second.add_to_hass(hass)
    assert await async_migrate_entry(hass, second) is True
    assert first.unique_id == key
    assert second.unique_id is None
    assert second.version == CONFIG_VERSION


async def test_migrate_rejects_a_future_schema_without_rewriting(
    hass: HomeAssistant,
) -> None:
    """HA may not call the hook for a future version; the hook still refuses."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ai_task pool",
        version=CONFIG_VERSION + 1,
        data=build_entry("ai_task").data,
    )
    assert await async_migrate_entry(hass, entry) is False


async def test_a_schema_from_the_future_is_not_guessed_at(
    hass: HomeAssistant,
) -> None:
    """Rejecting unknown versions is why the migrate hook exists at all."""
    assert await async_setup_component(hass, "ai_task", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ai_task pool",
        version=CONFIG_VERSION + 1,
        data=build_entry("ai_task").data,
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
