# AGENTS.md

This file provides guidance to Agentic Code when working with code in this repository.

## What this is

A Home Assistant custom integration (`custom_components/ai_pool`, HACS-installable) that
fronts several AI provider entities with **one** pool entity, rotating calls to spread
per-model daily quotas and failing over when a provider refuses. Four pool types:
`ai_task`, `conversation`, `tts`, `stt`. Requires Python 3.13+ and Home Assistant
2026.9.0+. Declared integration quality scale is **bronze** (`manifest.json`).

The product is quota split across **accounts** (API keys / config entries), not across
entity names. Two Google keys on `gemini-flash-latest` is the intended setup.

## Commands

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt

.venv/bin/pytest tests -q                          # full suite (Linux/macOS only)
.venv/bin/pytest tests/test_pool.py -q             # one file
.venv/bin/pytest tests/test_pool.py::test_name -q  # one test
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
pip install -r requirements-docs.txt && mkdocs serve   # http://127.0.0.1:8000
```

CI uses **Python 3.14** and pins `pytest-homeassistant-custom-component` in
`requirements-test.txt` (must match the oldest row of `.github/workflows/ci.yml`).
`scripts/component_requirements.py` reads the fronted components' pip requirements
from the *installed* HA manifests — that is how the test job gets
`ai_task`/`tts`/`stt` importable without pinning their deps twice.

A second workflow (`.github/workflows/validate.yml`) runs `hassfest` and HACS
validation, including a weekly cron. Pushes to `main` also publish the
[Material for MkDocs](https://fiveelements.github.io/ha-ai-pool/) site
(`.github/workflows/docs.yml`).

### Windows

The full suite cannot run natively — `pytest-homeassistant-custom-component` imports
`fcntl`. Only the provider-independent tests work:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_errors.py tests/test_strategies.py -q --noconftest
```

Docker Desktop is the local stand-in for CI. Do not claim a HA-dependent change is
tested until this (or Ubuntu CI) has run:

```bash
docker run --rm \
  -v "$PWD:/src" -v ha-ai-pool-pip:/root/.cache/pip -w /src \
  python:3.14-bookworm bash -lc '
    pip install -q -U pip
    pip install -q pytest-homeassistant-custom-component==0.13.362 pytest-cov
    python scripts/component_requirements.py > /tmp/reqs.txt
    pip install -q -r /tmp/reqs.txt
    pytest tests -q --tb=short
  '
```

On PowerShell, mount `C:\project\ai-project\ha-ai-pool:/src` (or `${PWD}:/src`) the
same way. Keep the harness pin identical to `requirements-test.txt`. The named volume
caches wheels so the second run is just pytest.

### Releasing

Bump `version` in **both** `custom_components/ai_pool/manifest.json` and
`pyproject.toml`, then `git tag vX.Y.Z && git push origin vX.Y.Z`. The release
workflow refuses to publish if tag and manifest disagree. `hacs.json`'s
`homeassistant` key is the supported floor and must match the oldest entry in the CI
matrix.

Do not raise `quality_scale` in the manifest above bronze until `test-coverage` in
`quality_scale.yaml` is measured (Silver wants ≥95%) and that rule is `done`.

## Architecture

The whole design is one idea: **`AIPool.async_execute(run)` in `pool.py` is
provider-agnostic.** Platforms supply a `run(entity_id) -> Awaitable[T]` callable that
does the real work against one member; every decision about *which* member and *what to
do when it fails* lives in the pool. Adding behaviour to routing means touching
`pool.py`, never the four platform files.

| Module | Role |
| ------ | ---- |
| `pool.py` | `AIPool`: member selection, the failover loop, verdict application, events, repairs. The core. |
| `errors.py` | `classify()` — maps an exception/message to a `FailureKind`. Pure, no HA imports. |
| `strategies.py` | `order_candidates()` — pure functions over plain `Candidate` data, no HA instance needed. |
| `store.py` | `UsageStore`/`PoolState`/`MemberState` — persisted counters, day rollover, rolling per-minute request log. |
| `views.py` | `MemberView` — the frozen read model every sensor, diagnostic and test consumes. |
| `models.py` | Heuristic model *and* provider `config_entry_id` behind a member (subentry first). `shared_account_models()` is the duplicate predicate. |
| `config_flow.py` | Create + options. Pool type is chosen once. STT buffer is shown in MB, stored in bytes. |
| `entity.py` | Shared identity for the four pool entities. Names the entity explicitly (see invariants). |
| `__init__.py` | Loads one of the four platforms plus sensors; `ai_pool.reset_member`; prunes orphan member sensors. |
| `ai_task.py` / `conversation.py` / `tts.py` / `stt.py` | Thin adapters: build `run`, call `async_execute`, translate the result. One is loaded per pool, chosen by `POOL_PLATFORM`. |
| `sensor.py` / `binary_sensor.py` | Diagnostics only (calls + latency per member, fallback rate, no-healthy-member problem sensor). |
| `diagnostics.py` | Config-entry dump. Nothing to redact: the pool holds no credentials. |

`entry.runtime_data` holds the `AIPool`. Pool type is immutable after creation because it
decides which platform loads; any options change triggers a full reload.

Observability that is not a sensor: `ai_pool_failover` / `ai_pool_exhausted` events, a
`duplicate_model` repair (same account + same model only), and `ai_pool.reset_member`.

## Invariants worth knowing before changing routing

These are deliberate and load-bearing; several have tests pinning them.

- **A member is never dropped, only demoted.** Exhausted/cooling/throttled members go to
  a last-resort group and are still tried. Declared limits are the user's estimate, and
  "fails loudly" beats "never runs". The one exception is `disabled` (auth).
- **QUOTA is matched before AUTH** in `_PATTERNS`. Providers return spent allowances as
  `403` as readily as `429`, and AUTH is the only permanent verdict.
- **The round-robin cursor advances by one modulo `CURSOR_MODULUS` (2520)**, not modulo
  the live queue length — taking it modulo a shrinking group skews rotation.
- **The day roll has exactly two call sites**: the request path (where it must be exact)
  and a midnight `async_track_time_change`. Read paths (`snapshot`, `member_status`,
  sensors) must stay pure — they compare against `store.today()` instead of mutating.
- **`calls_today` (successes) and `requests_today` (every attempt) bracket the provider's
  own counter.** Routing uses the optimistic one on purpose.
- **Cooldowns double per consecutive capacity refusal** up to `MAX_COOLDOWN`; only a
  *success* resets `cooldown_strikes`. Cooldown is per **member**, not per model.
- **A capacity skip is per account, not per model.** A 503 / "high demand" on one API
  key does not implicate the other keys. Only other members of the same config entry on
  that model are skipped for the rest of *this* request. A skip is not charged as an
  attempt. Unknown account or model concludes nothing (no skip).
- **The duplicate-model repair is the same shape.** Two accounts on `gemini-flash-latest`
  are the quota split; two entities of *one* config entry on that model are the same
  membership listed twice. `duplicate_models()` reads live `member_model` /
  `member_config_entry_id`, not the sensor cache — a repair that lags an options change
  used to keep warning about an account the user had just split.
- **Reloading the entry re-admits disabled members** (`clear_disabled`), as does the
  `ai_pool.reset_member` service. That is the only escape from an auth disable.
- **Unreadable model or account reports `None` and concludes nothing** — never a false
  duplicate match. `member_model()` is cached (`MODEL_CACHE_TTL`) because every sensor
  asks for every member; the repair path must not use that cache.
- The pool excludes its own entities from member pickers (`_own_entities`), or a pool
  could contain itself.
- **The pool entity stays available** when no member can serve. Trouble is the problem
  sensor and the events, not `unavailable` — a call must still be able to fail loudly.
  Do not flip `entity-unavailable` to `done` by hiding the pool.
- **The pool entity is named with `_attr_name = entry.title`**, not `has_entity_name`.
  The TTS manager reads `entity.name` and refuses an engine whose name is unset;
  `has_entity_name` with `name=None` would do that, and a translation key would
  double-name the device's only primary entity. Diagnostic sensors *do* use
  `has_entity_name`.
- **STT buffer: megabytes in the form, bytes in storage.** `_stt_buffer_mb` /
  `_policy_from_input` in `config_flow.py` are the conversion. The clip comparison
  measures bytes. The field is only shown for `stt` pools.
- **Fallback rate is `None` (HA `unknown`) when `requests_today` is 0.** Zero percent
  would look like "the preference order is perfect" before anything has run.

## Quality scale

`custom_components/ai_pool/quality_scale.yaml` is the checklist. Bronze rules are
`done` or `exempt`. Silver is blocked on `test-coverage`. Several exemptions are
product decisions, not leftovers — `has-entity-name`, `entity-unavailable`,
`log-when-unavailable`, `reauthentication-flow`, `test-before-configure`,
`test-before-setup`. Change the code *or* the comment, not the status alone.

`icon.png` at the repo root is the HACS brand. A listing in `home-assistant/brands`
is optional follow-up, not a merge blocker.

## Conventions

- Ruff with `D` (pydocstyle, pep257) enabled: **every module, class and function needs a
  docstring**; line length 88; target `py313`. Tests are exempt from `D100/D103/D104`.
- Comments in this codebase explain *why*, usually naming the failure mode the code
  exists to prevent, often in past tense ("it used to…"). Match that register; don't add
  comments that restate the code.
- New user-facing strings go in both `translations/en.json` and `translations/fr.json`.
  Config-flow fields need `data_description` as well as `name`.
- Storage and config-entry schemas both have migration hooks that currently do nothing —
  they exist so the first version bump doesn't break entries. Extend them, don't remove.
- `README.md` is the user documentation and is unusually precise about what the
  integration can and cannot know (notably: no provider reports remaining quota, and
  token counts are unavailable — only characters). Keep new claims in it honest and
  update it alongside behaviour changes.

### Tests that touch the entity registry

Register the member's provider config entry **before** `hass.states.async_set` (the
`available()` helper). A state occupying `ai_task.member_a` makes
`async_get_or_create(..., suggested_object_id="member_a")` mint `member_a_2`, and the
pool — still configured with `ai_task.member_a` — no longer sees the account. Same
account + same model fixtures must share one `MockConfigEntry`; two accounts need two
entries.
