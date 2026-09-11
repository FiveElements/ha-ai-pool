# AI Pool

Route AI calls across several providers from a **single** Home Assistant entity,
with rotation to spread daily quotas and automatic failover when a provider
refuses.

A pool publishes **one** entity in the domain it fronts. Automations call that
entity and know nothing about the routing:

```yaml
actions:
  - action: ai_task.generate_data
    data:
      task_name: Weather announcement
      entity_id: ai_task.morning_pool   # the pool, not a provider
      instructions: "{{ prompt }}"
    response_variable: report
```

Four pool types are supported:

| Pool type      | Publishes            | Delegates through                        |
| -------------- | -------------------- | ---------------------------------------- |
| `ai_task`      | `ai_task.*`          | `ai_task.async_generate_data`            |
| `conversation` | `conversation.*`     | `conversation.async_converse`            |
| `tts`          | `tts.*`              | `tts.async_get_media_source_audio`       |
| `stt`          | `stt.*`              | the member entity's audio stream handler |

## What this actually buys you

**Quota rotation.** Free tiers are commonly metered *per model*, so alternating
between two models on the same API key gives you two daily counters rather than
one. Rotating across three providers multiplies it again.

**Failover that knows why.** A provider that is momentarily overloaded should be
retried in five minutes; one that is out of allowance should sit out until
tomorrow; one with a bad API key should never be called again. These are
different situations and the pool treats them differently.

## The honest limitation

!!! warning "No provider reports remaining quota"

    The pool can only count *its own* calls and compare them against a limit
    you type in. It cannot see what the same API key spent elsewhere — another
    integration, a script, your phone.

So the two halves of this integration have very different reliability:

- **Failover on error is exact.** The provider told us it refused.
- **Rotation on quota is an estimate.** It steers traffic away from a member you
  *believe* is spent.

That asymmetry is deliberate: declared limits only influence *ordering*, and a
member believed to be exhausted is still tried as a last resort. A wrong guess
about a quota should never turn into a silent no-op.
