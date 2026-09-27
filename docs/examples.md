# Examples

Complete automations, ready to paste into the automation editor's YAML mode.
Replace the entity ids with your own; a pool's entity id is shown on its
device page.

## Blueprint: act when a pool could not serve

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FFiveElements%2Fha-ai-pool%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fai_pool%2Fnotify_on_exhausted.yaml)

[`notify_on_exhausted.yaml`](https://github.com/FiveElements/ha-ai-pool/blob/main/blueprints/automation/ai_pool/notify_on_exhausted.yaml)
runs your actions whenever the chosen pool fires `ai_pool_exhausted`: every
member it tried refused, or it had no usable member at all. Pick the pool and
add, for example, a notification:

```yaml
action: notify.mobile_app_phone
data:
  title: "{{ trigger.event.data.pool }} could not answer"
  message: >-
    {{ trigger.event.data.attempts }} of {{ trigger.event.data.members }}
    member(s) tried for {{ trigger.event.data.description }}.
```

## Morning announcement through a pool

The pool is called like any `ai_task` entity. When every member refuses, the
action raises; `continue_on_error` lets the automation fall back to a fixed
sentence instead of staying silent.

```yaml
alias: Morning weather announcement
triggers:
  - trigger: time
    at: "07:30:00"
actions:
  - action: ai_task.generate_data
    continue_on_error: true
    data:
      task_name: Weather announcement
      entity_id: ai_task.morning_pool
      instructions: >-
        Write two friendly sentences about today's weather:
        {{ states('weather.home') }},
        {{ state_attr('weather.home', 'temperature') }} degrees.
    response_variable: report
  - action: tts.speak
    target:
      entity_id: tts.voice_pool_text_to_speech
    data:
      media_player_entity_id: media_player.kitchen
      message: >-
        {{ report.data if report is defined and report.data is defined
           else 'The weather report is unavailable this morning.' }}
mode: single
```

## Tell me when a pool has had nobody healthy for a while

The **No healthy member** problem sensor turns on when every member is
exhausted, cooling down, throttled or unavailable. Last-resort members are
still tried, so a short blip is normal; waiting 15 minutes keeps the
notification for the case that needs you.

```yaml
alias: AI pool degraded
triggers:
  - trigger: state
    entity_id: binary_sensor.morning_pool_no_healthy_member
    to: "on"
    for:
      minutes: 15
actions:
  - action: persistent_notification.create
    data:
      title: "{{ device_attr(device_id(trigger.entity_id), 'name') }} is degraded"
      message: >-
        No member has been healthy for 15 minutes. Member statuses:
        {{ trigger.to_state.attributes | tojson }}
mode: single
```

## Log every failover

`ai_pool_failover` fires each time a member refuses and the pool moves on. A
logbook entry per failover shows which provider refused, and why, next to
the rest of the day's history.

```yaml
alias: Log AI pool failovers
triggers:
  - trigger: event
    event_type: ai_pool_failover
actions:
  - action: logbook.log
    data:
      name: "{{ trigger.event.data.pool }}"
      message: >-
        {{ trigger.event.data.member }} refused
        ({{ trigger.event.data.kind }}), attempt
        {{ trigger.event.data.attempt }}
mode: queued
max: 20
```

## Re-admit every member after a key rotation

A bad API key disables a member until the entry is reloaded or
`ai_pool.reset_member` is called. After you replace a key in the provider
integration, one button re-admits every member of the pool:

```yaml
alias: Re-admit AI pool members
triggers:
  - trigger: state
    entity_id: input_button.ai_pool_readmit
actions:
  - action: ai_pool.reset_member
    data:
      pool: 01M1J3KZ0GTB2EDE0279N6R26J   # the pool's config entry
mode: single
```
