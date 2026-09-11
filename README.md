# AI Pool for Home Assistant

Route AI calls across several providers from a single entity, with rotation to
spread daily quotas and automatic failover when a provider refuses.

[![CI](https://github.com/FiveElements/ha-ai-pool/actions/workflows/ci.yml/badge.svg)](https://github.com/FiveElements/ha-ai-pool/actions/workflows/ci.yml)
[![Validate](https://github.com/FiveElements/ha-ai-pool/actions/workflows/validate.yml/badge.svg)](https://github.com/FiveElements/ha-ai-pool/actions/workflows/validate.yml)
[![Docs](https://img.shields.io/badge/docs-Material_for_MkDocs-526CFE?logo=materialformkdocs)](https://fiveelements.github.io/ha-ai-pool/)

A pool publishes **one** entity in the domain it fronts. Your automations call
that entity and know nothing about the routing:

```yaml
actions:
  - action: ai_task.generate_data
    data:
      task_name: Weather announcement
      entity_id: ai_task.morning_pool   # the pool, not a provider
      instructions: "{{ prompt }}"
    response_variable: report
```

Four pool types are supported, each fronting its own domain:

| Pool type      | Publishes            | Delegates through                        |
| -------------- | -------------------- | ---------------------------------------- |
| `ai_task`      | `ai_task.*`          | `ai_task.async_generate_data`            |
| `conversation` | `conversation.*`     | `conversation.async_converse`            |
| `tts`          | `tts.*`              | `tts.async_get_media_source_audio`       |
| `stt`          | `stt.*`              | the member entity's audio stream handler |

## Documentation

The wiki is a [Material for MkDocs](https://fiveelements.github.io/ha-ai-pool/)
site, published from `docs/` on every push to `main`:

| Page | Contents |
| ---- | -------- |
| [Home](https://fiveelements.github.io/ha-ai-pool/) | What a pool is, and what it cannot know |
| [Install](https://fiveelements.github.io/ha-ai-pool/install/) | HACS, manual install, removal, parameters |
| [Configuration](https://fiveelements.github.io/ha-ai-pool/configuration/) | Strategies and failure handling |
| [Routing](https://fiveelements.github.io/ha-ai-pool/routing/) | Quotas, 503 vs 429, cooldowns, accounts |
| [Observability](https://fiveelements.github.io/ha-ai-pool/observability/) | Sensors, events, `ai_pool.reset_member` |
| [Troubleshooting](https://fiveelements.github.io/ha-ai-pool/troubleshooting/) | Symptoms, causes, fixes |
| [Platforms](https://fiveelements.github.io/ha-ai-pool/platforms/) | Notes per `ai_task` / conversation / TTS / STT |
| [Architecture](https://fiveelements.github.io/ha-ai-pool/architecture/) | Modules, request path, invariants |
| [Development](https://fiveelements.github.io/ha-ai-pool/development/) | Tests, quality scale, releasing |

## What this actually buys you

**Quota rotation.** Free tiers are commonly metered *per model*, so alternating
between two models on the same API key gives you two daily counters rather than
one. Rotating across three providers multiplies it again.

**Failover that knows why.** A provider that is momentarily overloaded should be
retried in five minutes; one that is out of allowance should sit out until
tomorrow; one with a bad API key should never be called again. These are
different situations and the pool treats them differently.

## The honest limitation, read this first

**No provider reports its remaining quota to Home Assistant.** The pool can only
count *its own* calls and compare them against a limit you type in. It cannot
see what the same API key spent elsewhere — another integration, a script, your
phone.

So the two halves of this integration have very different reliability:

- **Failover on error is exact.** The provider told us it refused.
- **Rotation on quota is an estimate.** It steers traffic away from a member you
  *believe* is spent.

That asymmetry is deliberate in the design: declared limits only influence
*ordering*, and a member believed to be exhausted is still tried as a last
resort. A wrong guess about a quota should never turn into a silent no-op.

## Install

### HACS

Add `https://github.com/FiveElements/ha-ai-pool` as a custom repository of type
*Integration*, install **AI Pool**, restart Home Assistant, then add the
integration from *Settings → Devices & Services*.

### Manual

Copy `custom_components/ai_pool` into your Home Assistant `config/custom_components`
directory and restart.

### Removal

Delete the integration from *Settings → Devices & Services*. That removes the
pool entity, its diagnostic sensors, the persisted usage counters, and any
duplicate-model repair. Member provider integrations and their credentials are
left alone.

### Installation parameters

These are the fields on the three setup steps. Changing members or policy later
uses the same fields, except **pool type**, which is fixed at creation.

| Parameter | Step | Meaning |
| --------- | ---- | ------- |
| Name | 1 | Title of the pool entity and its device. |
| Pool type | 1 | Domain the pool publishes in (`ai_task`, `conversation`, `tts`, `stt`). |
| Members | 2 | Entities of that domain, in preference order. |
| Strategy | 2 | How the next healthy member is chosen. |
| Cooldown | 2 | Sit-out after a capacity refusal (seconds). Consecutive refusals double it. |
| Max attempts | 2 | Members tried per request before giving up. |
| Timeout | 2 | Seconds to wait for one member. `0` waits forever. |
| Audio retry buffer | 2 | Speech-to-text only. Megabytes kept so a second member can hear the same recording. |
| Requests per day | 3 | Declared daily allowance per member. `0` if unknown. |
| Requests per minute | 3 | Declared per-minute allowance per member. `0` if unknown. |
| Weight | 3 | Bias for `least_used` routing. |

## Configuration

Everything is configured in the UI, in three steps:

1. **Name and type** — which domain the pool fronts. This cannot be changed
   afterwards, because it decides which platform is loaded.
2. **Members and policy** — the member entities, in preference order, plus the
   selection strategy, the cooldown, the cap on attempts per call, and the
   per-member deadline. Speech-to-text pools also set the audio retry buffer
   (megabytes kept in memory so a second member can hear the same recording).
3. **Daily allowances** — a declared limit and a weight per member. Use `0` when
   you do not know the limit.

Members are always picked from the pool's own domain, and pool entities are
excluded from the picker so a pool can never contain itself.

### Strategies

| Strategy      | Behaviour                                                          |
| ------------- | ------------------------------------------------------------------ |
| `round_robin` | Rotate on every call. This is what spreads load across quotas.     |
| `least_used`  | Whoever has the most allowance left goes first.                    |
| `priority`    | Always try in configured order. Pure failover, no load spreading.  |

`least_used` compares *shares* rather than raw counts, so a large allowance half
spent outranks a small one nearly spent. `weight` biases a member as if it had
proportionally more room.

### Failure handling

| Provider says                                         | Classified as | Consequence                       |
| ----------------------------------------------------- | ------------- | --------------------------------- |
| `RESOURCE_EXHAUSTED`, quota, billing                  | quota         | Out until the local day rolls     |
| `429`, `503`, rate-limit, high demand, overload       | capacity      | Cooldown, then eligible again     |
| `500`, `502`, `504`, timeout, connection              | transient     | Next member, no penalty           |
| `401`, `403`, invalid API key                         | auth          | Disabled; retrying cannot help    |
| `400`, not supported, response schema                 | unsupported   | Next member                       |
| anything else                                         | unknown       | Next member, recorded for triage  |

Home Assistant flattens provider errors into a single exception type, so the
status is only recoverable from the message text. That is why classification is
pattern-based, and why `unknown` exists rather than being guessed at.

## Observability

The pool wraps every call, so it is the one place that can measure providers
without instrumenting any of them. Three diagnostic sensors, each answering a
different question:

| Sensor | Question it answers |
| ------ | ------------------- |
| `<member> calls` | Who is doing the work, and against which allowance? Status, remaining allowance, success rate, cooldown, last error, one `failures_<kind>` counter per observed failure kind, and the rate-limit counters below. |
| `<member> latency` | Who answers fast enough to deserve going first? Duration of the last successful call, with today's average, min, max and a recent-window average. **Disabled by default** — enable it when you want the chart. |
| `Fallback rate` | Is the preference order any good? Share of today's requests that needed more than one member, with the attempt counters behind it. |

The latency sensor is a `measurement` with `device_class: duration`, so the
recorder keeps long-term statistics: providers can be charted against each
other over weeks, which is the comparison that tells you how to order and
weight them. It records **successful** calls only — a refusal's duration
measures how long the provider took to say no, which is a different question.

A fallback rate near zero means the first choice is serving. A high one means
the pool is quietly working around an order that should be changed.

### Tracking rate limits

Providers meter three dimensions: requests per minute, input **tokens** per
minute, and requests per day. Two of the three can be measured from here, and
the calls sensor carries them as attributes:

| Attribute | Meaning |
| --------- | ------- |
| `requests_last_minute` | Requests sent to this member in the last 60 seconds — the RPM dimension, rolling and pruned by age. |
| `rpm_limit`, `rpm_remaining` | Headroom against the per-minute allowance you declared. `null` when none is declared. A member at its ceiling reports `status: throttled` and is demoted to last resort — like every declared limit it only reorders, because the number is your estimate. |
| `requests_today` | Requests sent today, refusals included. |
| `rpd_remaining` | Headroom against the daily allowance, counted from `requests_today`. |
| `input_chars_last_minute`, `input_chars_today` | How much input was sent, in characters. |

Three things about those numbers are worth being explicit about.

**Token counts are not available.** Home Assistant's `ai_task`, `conversation`,
`tts` and `stt` APIs return the result, never the provider's usage report, so
the integration cannot know how many tokens a request cost. Characters are what
can honestly be measured; roughly four characters per token is the usual rule
of thumb, so the TPM dimension can be estimated but not tracked.

**`calls_today` and `requests_today` bracket the truth.** A provider charges a
request against your allowance when it receives it, but a request it refuses
with a server error probably costs nothing. `calls_today` counts successes only,
`requests_today` counts every attempt, and the provider's own counter sits
somewhere between the two. The routing decision deliberately uses the
optimistic one: an announcement that fails loudly beats one that never runs.

**Limits have to be typed in.** Google no longer publishes per-model figures on
[its rate-limit page](https://ai.google.dev/gemini-api/docs/rate-limits) — read
your own at [AI Studio](https://aistudio.google.com/rate-limit). Two details
from that page shape how a pool should be built: limits are applied **per
project, not per API key**, so two accounts really do get independent
allowances; and "specified rate limits are not guaranteed and actual capacity
may vary", so a member can refuse while well inside its declared limit.

That last point is why `failures_capacity` and `failures_quota` are counted
separately. A `429 RESOURCE_EXHAUSTED` / quota message is your limit; a bare
`429 Too Many Requests` or a `503 UNAVAILABLE` is this key being told the model
is busy. Another account on the same model is
still worth asking: that 503 is not a signal about the other keys. The pool
only skips other members of **the same account** on that model for the rest
of *this* request. Spreading daily allowance across accounts remains the
reason to keep both members.

### Members that are secretly the same account

Two API keys on `gemini-flash-latest` are two daily counters, which is the
point of a pool. Two entities of **one** account on that model are the same
membership listed twice: they share a quota and fail together.

The pool therefore reads each member's model *and* the provider config entry
that owns it — the subentry first, for providers that publish several entities
per account. It raises a **repair** only when members share a model *and* an
account. And on a capacity failover it **skips** other members of that same
account on the model that just refused — not the other keys. A skip is not
charged as an attempt.

Providers name that option as they please and are free to change it, so this is
a heuristic: an unreadable model is reported as `null` and carries no
conclusion, never a false match.

### When the pool cannot serve

Two things watch for the failure that used to be silent - every member refusing,
the call raising, and an announcement simply never playing.

A **problem sensor** per pool, on when no member is healthy (preferred), with
each member's status as attributes. Exhausted, cooling or throttled members are
still tried as last resort, so the sensor can be on while a call still
succeeds. It is polled rather than event-driven,
because two of the three ways it changes - a cooldown expiring, a member entity
going unavailable - happen without the pool being involved.

Two **events** on the Home Assistant bus, so an automation can react without
polling anything:

| Event | Fired when | Payload |
| ----- | ---------- | ------- |
| `ai_pool_failover` | a member fails and the pool moves on | `member`, `model`, `kind`, `message`, `attempt`, `description` |
| `ai_pool_exhausted` | every attempted member failed | `attempts`, `members`, `description` |

Both also carry `entry_id`, `pool` and `pool_type`, so one automation can watch
every pool and branch on the payload. A working pool fires nothing.

### Giving up on a member

Each attempt has a deadline, **120 seconds** by default, configurable per pool
and disabled with 0. Past it the member is abandoned and the next one is tried.
A deadline is not latency-based routing: it never reorders members, it only
stops one from holding a request open forever. Timeouts are counted as their own
failure kind, apart from a provider's refusal, because "too slow for us" and "it
said no" call for different fixes.

### Cooldowns that lengthen, and how to end one

Capacity refusals arrive in clusters, so each consecutive refusal doubles the
member's cooldown, up to an hour. A **success** resets it - nothing else is
evidence that the provider has recovered - and `cooldown_strikes` on the calls
sensor explains an unusually long wait.

A refusal that names a spent allowance is read as a quota problem even when it
arrives as `403`, which some providers do. An authentication verdict is the one
thing that stops a member from ever being tried again, so evidence of a quota
outranks a bare status code.

An authentication failure disables a member, and that verdict is persisted: one
revoked key used to retire a provider for good, with deleting the config entry
as the only way back. Two things end it now. Reloading the entry re-admits every
disabled member, which is the closest thing to the user saying "try again". And
the `ai_pool.reset_member` service clears the cooldown, the spent-allowance mark
and the disable on one member, or on all of them:

```yaml
action: ai_pool.reset_member
data:
  pool: 01M1J3KZ0GTB2EDE0279N6R26J   # the pool's config entry
  member: ai_task.google_ai_task     # optional; omit to reset every member
  clear_counters: false              # optional; see below
```

One allowance the service cannot lift on its own: a member counted as spent
against the daily limit *you declared*. That verdict comes from the pool's own
counter, so the only way to make the member eligible again before midnight is
to forget what it has done today — which is what `clear_counters: true` does,
at the cost of that member's metrics for the day. The service reports which
members were actually holding something back, so "nothing to reset" means
nothing was.

`Download diagnostics` on the config entry returns the same per-member data
plus the routing policy and the pool-wide counters.

Counters are persisted, so a restart at 18:00 does not hand a spent member a
fresh allowance. Day counters reset on the local calendar day; the recent
latency window deliberately does not, because "how fast is it right now" is
not a question about today.

### Data updates

The pool is not a polling integration. Counters, latency and the fallback rate
update **when a call is routed**. A restart does not reset today's counts:
usage is persisted.

The **problem sensor** polls once a minute, because a cooldown can expire or a
member can go unavailable without the pool seeing a call. Day counters roll at
local midnight and again on the next request if midnight was missed. Sensors
never roll the day themselves.

There is no user-configurable scan interval for the routed platforms: a call
is the update. Do not lower the problem sensor's poll in the hope of seeing
quota sooner; the provider does not report remaining quota at all.

## Troubleshooting

Symptoms, causes and fixes live on the
[troubleshooting](https://fiveelements.github.io/ha-ai-pool/troubleshooting/)
wiki page. The short list:

| Symptom | First check |
| ------- | ----------- |
| Announcement never plays, pool stays available | Problem sensor statuses, then `ai_pool_exhausted` |
| Repair about a shared model | Same **account** (config entry) twice; two keys on one model are fine |
| One 503 skips the other Flash member | They share a config entry; split API keys if you meant two accounts |
| High fallback rate | First member's `failures_<kind>` |
| Missing latency sensors | Disabled by default — enable in the entity registry |
| Truncated STT transcript | Raise the audio retry buffer; clipped audio gets no failover |
| Cannot add a second pool over the same members | That would double-count the allowance. Identity is the exact set: `[A, B]` and `[A, C]` are different pools. |
| Cannot change pool type | Create a new pool; type decides which platform loads |

Configure or **Reconfigure** on the config entry edits members and policy
without deleting the pool. Reload the entry (or `ai_pool.reset_member`) to
re-admit a member disabled by a bad API key.

## Per-type notes

- **`ai_task`** — attachments are not supported. They arrive already resolved
  and there is no supported way to pass a resolved attachment to another entity,
  so Home Assistant rejects such calls before they reach the pool.
- **`conversation`** — a member answering with an error response counts as a
  failure, otherwise the pool would return "sorry" from the first broken member
  and never reach a working one. Languages are advertised as match-all.
- **`tts`** — languages and options are the *union* across members; a member
  that cannot handle a request raises and the next one is tried.
- **`stt`** — audio is buffered so a second member can be given the same
  recording. The buffer defaults to 8 MB and is set in the members step of
  the UI. Audio *format* capabilities are the *intersection* across members,
  because the pipeline encodes once before any member is chosen. A recording
  larger than the buffer limit is clipped to what fits and gets **one attempt
  with no failover**: handing the same half-sentence to a second member cannot
  produce a better transcript. The transcript that comes back is of the clipped
  audio, so it may be incomplete — the warning in the log says so.

## Development

Longer notes (architecture, tests, quality scale, releasing) live on the
[development](https://fiveelements.github.io/ha-ai-pool/development/) and
[architecture](https://fiveelements.github.io/ha-ai-pool/architecture/) wiki
pages.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest tests -q
.venv/bin/ruff check custom_components tests
```

The Home Assistant test harness imports `fcntl` and therefore **only runs on
Linux and macOS**. On Windows the provider-independent tests still run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_errors.py tests/test_strategies.py -q --noconftest
```

CI runs the full suite on Ubuntu against the Home Assistant versions listed
in `.github/workflows/ci.yml` (currently the declared floor, **2026.9.0**),
plus `hassfest` and HACS validation. Pull requests also build the docs with
`mkdocs build --strict`. The harness pins one Home
Assistant version per release, so the matrix selects versions by harness
version; `scripts/component_requirements.py` then reads the fronted components'
own dependencies from the installed manifests, which keeps them right across
those versions.

### Where this integration stands against the quality scale

Progress is tracked in
[`quality_scale.yaml`](custom_components/ai_pool/quality_scale.yaml) against
Home Assistant's [integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
The manifest declares **platinum**. Silver is held by `--cov-fail-under=95`
in CI. A listing in the Home Assistant brands repository can follow the
in-repo `icon.png`.

Rules this integration keeps as exemptions:

- **`has-entity-name`** — the pool entity is named explicitly. `Entity.name`
  returns `_attr_name` verbatim, and the device name is composed in later and
  only for the friendly name; the tts manager reads `entity.name` directly and
  refuses an engine whose name is not set. The alternative that satisfies the
  rule would name the entity twice over, since the device *is* the pool and
  carries one primary entity.
- **`entity-unavailable`** — pool entities stay available and report trouble
  through a problem sensor and events instead. A pool with no healthy member
  can still be worth calling: a declared limit is an estimate, and an
  announcement that fails loudly beats one that never runs.

`reauthentication-flow`, `test-before-configure` and `test-before-setup` do not
apply — a pool holds no credentials and opens no connection; the member
integrations own both.

### Supported Home Assistant versions

Requires **2026.9.0** or newer, which is both the minimum declared in
`hacs.json` and the version CI tests against. Earlier versions are not
supported: 2026.8.3 was, and the code still avoids nothing on its account, but
it is no longer tested and no longer installable through HACS.

### Releasing

Bump `version` in `custom_components/ai_pool/manifest.json`, then push a matching
tag:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The release workflow refuses to publish when the tag and the manifest disagree,
builds `ai_pool.zip`, and attaches it to a GitHub release.

## License

MIT
