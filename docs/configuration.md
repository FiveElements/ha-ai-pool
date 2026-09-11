# Configuration

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

An existing pool is edited from **Configure** (options) or **Reconfigure** on
the config entry. Configure opens a menu: members and policy, or daily
allowances. Reconfigure still walks both. Neither changes the pool type.


## Strategies

| Strategy      | Behaviour                                                          |
| ------------- | ------------------------------------------------------------------ |
| `round_robin` | Rotate on every call. This is what spreads load across quotas.     |
| `least_used`  | Whoever has the most allowance left goes first.                    |
| `priority`    | Always try in configured order. Pure failover, no load spreading.  |

`least_used` compares *shares* rather than raw counts, so a large allowance half
spent outranks a small one nearly spent. `weight` biases a member as if it had
proportionally more room.

## Failure handling

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
