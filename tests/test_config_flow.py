"""Config and options flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ai_pool.config_flow import (
    _entry_pool_key,
    _pool_key,
    _stt_buffer_mb,
)
from custom_components.ai_pool.const import (
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
    DEFAULT_STT_BUFFER_LIMIT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    STRATEGY_LEAST_USED,
    STRATEGY_ROUND_ROBIN,
)

A = "ai_task.member_a"
B = "ai_task.member_b"
STT_A = "stt.member_a"
STT_B = "stt.member_b"


def _schema_keys(result: dict) -> dict:
    """Index a form schema by field name."""
    return {str(key): key for key in result["data_schema"].schema}


def _section_defaults(result: dict, index: int) -> dict:
    """Index a numbered member section's inner fields."""
    section_key = f"member_{index}"
    for key, value in result["data_schema"].schema.items():
        if str(key) == section_key:
            return {str(inner): inner for inner in value.schema.schema}
    raise KeyError(section_key)


def _limits_input(*rows: tuple[int, int, int]) -> dict:
    """Build a limits-step submit payload from (daily, rpm, weight) rows."""
    return {
        f"member_{index}": {
            CONF_DAILY_LIMIT: daily,
            CONF_RPM_LIMIT: rpm,
            CONF_WEIGHT: weight,
        }
        for index, (daily, rpm, weight) in enumerate(rows, start=1)
    }


async def _start_members_step(hass: HomeAssistant, name: str, pool_type: str) -> dict:
    """Walk a new flow as far as the members-and-policy form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": name, CONF_POOL_TYPE: pool_type}
    )


async def _choose_options(hass: HomeAssistant, entry_id: str, choice: str) -> dict:
    """Open Configure and pick members-and-policy or allowances."""
    result = await hass.config_entries.options.async_init(entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert list(result["menu_options"]) == ["members", "limits"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )


def test_stt_buffer_form_shows_whole_megabytes() -> None:
    assert _stt_buffer_mb(8 * 1024 * 1024) == 8
    assert _stt_buffer_mb(4 * 1024 * 1024) == 4
    assert _stt_buffer_mb(None) == 8


async def test_full_flow_creates_a_pool(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Gemini pool", CONF_POOL_TYPE: "ai_task"}
    )
    assert result["step_id"] == "members"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A, B],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: 90,
        },
    )
    assert result["step_id"] == "limits"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _limits_input((250, 10, 1), (250, 15, 2)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gemini pool"

    data = result["data"]
    assert data[CONF_POOL_TYPE] == "ai_task"
    assert data[CONF_STRATEGY] == STRATEGY_ROUND_ROBIN
    assert data[CONF_TIMEOUT] == 90
    assert CONF_STT_BUFFER_LIMIT not in data
    assert data[CONF_MEMBERS] == [
        {
            "entity_id": A,
            CONF_DAILY_LIMIT: 250,
            CONF_RPM_LIMIT: 10,
            CONF_WEIGHT: 1,
        },
        {
            "entity_id": B,
            CONF_DAILY_LIMIT: 250,
            CONF_RPM_LIMIT: 15,
            CONF_WEIGHT: 2,
        },
    ]
    # The name is the entry title, not a config value.
    assert "name" not in data


async def test_members_step_rejects_an_empty_selection(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Empty", CONF_POOL_TYPE: "tts"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MEMBERS: "no_members"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: ["tts.member_a"],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "limits"


async def test_options_flow_edits_quotas_without_revisiting_members(
    hass: HomeAssistant,
) -> None:
    """Configure must offer the allowances form as its own destination.

    The page used to sit behind members-and-policy, so changing a daily
    limit after creation looked impossible.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
            CONF_MEMBERS: [
                {
                    "entity_id": A,
                    CONF_DAILY_LIMIT: 777,
                    CONF_RPM_LIMIT: 12,
                    CONF_WEIGHT: 4,
                }
            ],
        },
    )
    entry.add_to_hass(hass)

    result = await _choose_options(hass, entry.entry_id, "limits")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "limits"
    schema = _section_defaults(result, 1)
    assert schema[CONF_DAILY_LIMIT].default() == 777
    assert schema[CONF_RPM_LIMIT].default() == 12
    assert schema[CONF_WEIGHT].default() == 4

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((50, 8, 2)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    member = entry.data[CONF_MEMBERS][0]
    assert member[CONF_DAILY_LIMIT] == 50
    assert member[CONF_RPM_LIMIT] == 8
    assert member[CONF_WEIGHT] == 2
    # Jumping to allowances must not reset the routing policy.
    assert entry.data[CONF_STRATEGY] == STRATEGY_ROUND_ROBIN
    assert entry.data[CONF_COOLDOWN] == 300
    assert entry.data[CONF_TIMEOUT] == DEFAULT_TIMEOUT


async def test_options_flow_quotas_keep_an_stt_buffer(
    hass: HomeAssistant,
) -> None:
    """An allowances-only save must not drop the audio retry buffer."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Listen",
        data={
            CONF_POOL_TYPE: "stt",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_STT_BUFFER_LIMIT: 4 * 1024 * 1024,
            CONF_MEMBERS: [{"entity_id": STT_A, CONF_DAILY_LIMIT: 0, CONF_WEIGHT: 1}],
        },
    )
    entry.add_to_hass(hass)

    result = await _choose_options(hass, entry.entry_id, "limits")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((20, 0, 1)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_STT_BUFFER_LIMIT] == 4 * 1024 * 1024
    assert entry.data[CONF_MEMBERS][0][CONF_DAILY_LIMIT] == 20


async def test_options_flow_updates_members_and_policy(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    entry.add_to_hass(hass)

    result = await _choose_options(hass, entry.entry_id, "members")
    assert result["step_id"] == "members"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A, B],
            CONF_STRATEGY: STRATEGY_LEAST_USED,
            CONF_COOLDOWN: 60,
            CONF_MAX_ATTEMPTS: 2,
        },
    )
    assert result["step_id"] == "limits"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((100, 0, 1), (500, 5, 3)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The options flow writes back into `data` rather than leaving a second
    # copy of the configuration in `options`, so `data` is the whole truth.
    assert result["data"] == {}
    assert entry.options == {}
    assert entry.data[CONF_STRATEGY] == STRATEGY_LEAST_USED
    assert entry.data[CONF_COOLDOWN] == 60
    assert len(entry.data[CONF_MEMBERS]) == 2
    # The pool type is not editable and must survive the round trip.
    assert entry.data[CONF_POOL_TYPE] == "ai_task"


async def test_options_flow_keeps_existing_limits_as_defaults(
    hass: HomeAssistant,
) -> None:
    """Re-opening options must not silently zero a declared allowance."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [
                {
                    "entity_id": A,
                    CONF_DAILY_LIMIT: 777,
                    CONF_RPM_LIMIT: 12,
                    CONF_WEIGHT: 4,
                }
            ],
        },
    )
    entry.add_to_hass(hass)

    result = await _choose_options(hass, entry.entry_id, "members")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
        },
    )
    schema = _section_defaults(result, 1)
    assert schema[CONF_DAILY_LIMIT].default() == 777
    assert schema[CONF_RPM_LIMIT].default() == 12
    assert schema[CONF_WEIGHT].default() == 4


async def test_members_step_exposes_timeout_with_the_documented_default(
    hass: HomeAssistant,
) -> None:
    result = await _start_members_step(hass, "Timeout", "ai_task")
    schema = _schema_keys(result)
    assert CONF_TIMEOUT in schema
    assert schema[CONF_TIMEOUT].default() == DEFAULT_TIMEOUT
    assert CONF_STT_BUFFER_LIMIT not in schema


async def test_stt_members_step_exposes_the_audio_buffer(
    hass: HomeAssistant,
) -> None:
    """Speech-to-text is the only type that has to keep the recording around."""
    result = await _start_members_step(hass, "Listen", "stt")
    schema = _schema_keys(result)
    assert CONF_STT_BUFFER_LIMIT in schema
    assert schema[CONF_STT_BUFFER_LIMIT].default() == 8


async def test_stt_flow_stores_the_buffer_in_bytes(
    hass: HomeAssistant,
) -> None:
    result = await _start_members_step(hass, "Listen", "stt")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [STT_A, STT_B],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
            CONF_STT_BUFFER_LIMIT: 4,
        },
    )
    assert result["step_id"] == "limits"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _limits_input((0, 0, 1), (0, 0, 1)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STT_BUFFER_LIMIT] == 4 * 1024 * 1024


async def test_creating_a_second_pool_over_the_same_members_aborts(
    hass: HomeAssistant,
) -> None:
    """Two pools on the same members would each spend the allowance twice."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Existing",
        unique_id=_pool_key("ai_task", [A, B]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [
                {"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1},
                {"entity_id": B, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1},
            ],
        },
    )
    existing.add_to_hass(hass)

    result = await _start_members_step(hass, "Copy", "ai_task")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            # Order is not identity: the same members backwards are still them.
            CONF_MEMBERS: [B, A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _limits_input((0, 0, 1), (0, 0, 1)),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_rejects_a_member_set_another_pool_already_covers(
    hass: HomeAssistant,
) -> None:
    first = MockConfigEntry(
        domain=DOMAIN,
        title="First",
        unique_id=_pool_key("ai_task", [A]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    first.add_to_hass(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        unique_id=_pool_key("ai_task", [B]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": B, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    second.add_to_hass(hass)

    result = await _choose_options(hass, second.entry_id, "members")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((100, 0, 1)),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_members"}
    schema = _section_defaults(result, 1)
    assert schema[CONF_DAILY_LIMIT].default() == 100
    assert schema[CONF_WEIGHT].default() == 1


async def test_options_flow_keeps_an_stt_buffer_as_the_default(
    hass: HomeAssistant,
) -> None:
    """Re-opening options must not silently restore the 8 MB default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Listen",
        data={
            CONF_POOL_TYPE: "stt",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_STT_BUFFER_LIMIT: 4 * 1024 * 1024,
            CONF_MEMBERS: [{"entity_id": STT_A, CONF_DAILY_LIMIT: 0, CONF_WEIGHT: 1}],
        },
    )
    entry.add_to_hass(hass)

    result = await _choose_options(hass, entry.entry_id, "members")
    schema = _schema_keys(result)
    assert schema[CONF_STT_BUFFER_LIMIT].default() == 4

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [STT_A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
            CONF_STT_BUFFER_LIMIT: 16,
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((0, 0, 1)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_STT_BUFFER_LIMIT] == 16 * 1024 * 1024
    assert entry.data[CONF_STT_BUFFER_LIMIT] != DEFAULT_STT_BUFFER_LIMIT


async def test_reconfigure_flow_updates_members_without_changing_pool_type(
    hass: HomeAssistant,
) -> None:
    """Reconfigure is how Gold wants an existing entry edited, not deleted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        unique_id=_pool_key("ai_task", [A]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    # Pool type is immutable, so reconfigure starts at members, not user.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "members"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A, B],
            CONF_STRATEGY: STRATEGY_LEAST_USED,
            CONF_COOLDOWN: 60,
            CONF_MAX_ATTEMPTS: 2,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    assert result["step_id"] == "limits"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _limits_input((100, 0, 1), (500, 5, 3)),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_POOL_TYPE] == "ai_task"
    assert entry.data[CONF_STRATEGY] == STRATEGY_LEAST_USED
    assert entry.data[CONF_COOLDOWN] == 60
    assert len(entry.data[CONF_MEMBERS]) == 2
    assert entry.options == {}
    assert entry.unique_id == _pool_key("ai_task", [A, B])


async def test_reconfigure_flow_rejects_a_member_set_another_pool_already_covers(
    hass: HomeAssistant,
) -> None:
    first = MockConfigEntry(
        domain=DOMAIN,
        title="First",
        unique_id=_pool_key("ai_task", [A]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    first.add_to_hass(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        unique_id=_pool_key("ai_task", [B]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": B, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    second.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": second.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _limits_input((100, 0, 1)),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # Second pool is unchanged: colliding is not a silent overwrite.
    assert [item["entity_id"] for item in second.data[CONF_MEMBERS]] == [B]


async def test_options_flow_recovers_from_an_empty_selection(
    hass: HomeAssistant,
) -> None:
    """Rejecting no members must not strand the flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    entry.add_to_hass(hass)

    result = await _choose_options(hass, entry.entry_id, "members")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MEMBERS: "no_members"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    assert result["step_id"] == "limits"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((100, 0, 1)),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_flow_clash_sees_an_unstamped_unique_id(
    hass: HomeAssistant,
) -> None:
    """A restored v1 entry with unique_id=None still owns its member set."""
    first = MockConfigEntry(
        domain=DOMAIN,
        title="First",
        unique_id=None,
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": A, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    first.add_to_hass(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        unique_id=_pool_key("ai_task", [B]),
        data={
            CONF_POOL_TYPE: "ai_task",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_MEMBERS: [{"entity_id": B, CONF_DAILY_LIMIT: 100, CONF_WEIGHT: 1}],
        },
    )
    second.add_to_hass(hass)

    result = await _choose_options(hass, second.entry_id, "members")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _limits_input((100, 0, 1)),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_members"}


async def test_reconfigure_flow_keeps_an_stt_buffer_as_the_default(
    hass: HomeAssistant,
) -> None:
    """Reconfigure must not silently restore the 8 MB default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Listen",
        unique_id=_pool_key("stt", [STT_A]),
        data={
            CONF_POOL_TYPE: "stt",
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_STT_BUFFER_LIMIT: 4 * 1024 * 1024,
            CONF_MEMBERS: [{"entity_id": STT_A, CONF_DAILY_LIMIT: 0, CONF_WEIGHT: 1}],
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    schema = _schema_keys(result)
    assert schema[CONF_STT_BUFFER_LIMIT].default() == 4

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MEMBERS: [STT_A],
            CONF_STRATEGY: STRATEGY_ROUND_ROBIN,
            CONF_COOLDOWN: 300,
            CONF_MAX_ATTEMPTS: 3,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
            CONF_STT_BUFFER_LIMIT: 16,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _limits_input((0, 0, 1)),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_STT_BUFFER_LIMIT] == 16 * 1024 * 1024


def test_entry_pool_key_without_members_is_unknown() -> None:
    """A draft with no members cannot own an identity yet."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=None,
        data={CONF_POOL_TYPE: "ai_task"},
    )
    assert _entry_pool_key(entry) is None
