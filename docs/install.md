# Install

## HACS

Add [`https://github.com/FiveElements/ha-ai-pool`](https://github.com/FiveElements/ha-ai-pool)
as a custom repository of type **Integration**, install **AI Pool**, restart
Home Assistant, then add the integration from *Settings → Devices & Services*.

## Manual

Copy `custom_components/ai_pool` into your Home Assistant
`config/custom_components` directory and restart.

Requires **Home Assistant 2026.9.0** or newer.

## Removal

Delete the integration from *Settings → Devices & Services*. That removes the
pool entity, its diagnostic sensors, the persisted usage counters, and any
duplicate-model repair. Member provider integrations and their credentials are
left alone.

## Installation parameters

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
