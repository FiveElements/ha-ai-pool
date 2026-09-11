# Observability

The pool wraps every call, so it is the one place that can measure providers
without instrumenting any of them.

## Diagnostic sensors

| Sensor | Question it answers |
| ------ | ------------------- |
| `<member> calls` | Who is doing the work, and against which allowance? Status, remaining allowance, success rate, cooldown, last error, one `failures_<kind>` counter per observed failure kind, and the rate-limit counters below. |
| `<member> latency` | Who answers fast enough to deserve going first? Duration of the last successful call, with today's average, min, max and a recent-window average. **Disabled by default** — enable it when you want the chart. |
| `Fallback rate` | Is the preference order any good? Share of today's requests that needed more than one member. `unknown` until the first request of the day. |

The latency sensor is a `measurement` with `device_class: duration`, so the
recorder keeps long-term statistics. It records **successful** calls only — a
refusal's duration measures how long the provider took to say no.

A fallback rate near zero means the first choice is serving. A high one means
the pool is working around an order that should be changed.

### Rate-limit attributes on the calls sensor

| Attribute | Meaning |
| --------- | ------- |
| `requests_last_minute` | Requests sent to this member in the last 60 seconds. |
| `rpm_limit`, `rpm_remaining` | Headroom against the per-minute allowance you declared. `null` when none is declared. At the ceiling the member reports `status: throttled` and is demoted. |
| `requests_today` | Requests sent today, refusals included. |
| `rpd_remaining` | Headroom against the daily allowance, counted from `requests_today`. |
| `input_chars_last_minute`, `input_chars_today` | How much input was sent, in characters. |

## When the pool cannot serve

A **problem sensor** per pool turns on when no member is in a state to serve,
with each member's status as attributes. It is polled rather than event-driven,
because a cooldown expiring or a member going unavailable can happen without
the pool being involved.

Two **events** on the Home Assistant bus:

| Event | Fired when | Payload |
| ----- | ---------- | ------- |
| `ai_pool_failover` | a member fails and the pool moves on | `member`, `model`, `kind`, `message`, `attempt`, `description` |
| `ai_pool_exhausted` | every attempted member failed | `attempts`, `members`, `description` |

Both also carry `entry_id`, `pool` and `pool_type`. A working pool fires nothing.

## Reset a member

An authentication failure disables a member and that verdict is persisted.
Reloading the entry re-admits every disabled member. The
`ai_pool.reset_member` service clears the cooldown, the spent-allowance mark
and the disable on one member, or on all of them:

```yaml
action: ai_pool.reset_member
data:
  pool: 01M1J3KZ0GTB2EDE0279N6R26J   # the pool's config entry
  member: ai_task.google_ai_task     # optional; omit to reset every member
  clear_counters: false              # optional
```

`clear_counters: true` also forgets today's counts, which is the only way to
make a member eligible again before midnight when the *declared* daily limit
is spent.

`Download diagnostics` on the config entry returns the same per-member data
plus the routing policy and the pool-wide counters.

Counters are persisted, so a restart at 18:00 does not hand a spent member a
fresh allowance. Day counters reset on the local calendar day; the recent
latency window does not.

## Data updates

The pool is not a polling integration. It does not fetch from a remote API on
a timer.

Counters, latency and the fallback rate update **when a call is routed** (the
request path notifies listeners; diagnostic sensors do not poll). A restart
does not reset today's counts: usage is persisted.

The **problem sensor** is the exception. It polls once a minute, because a
cooldown can expire or a member can go unavailable without the pool seeing a
call.

Day counters roll at local midnight and again on the next request if midnight
was missed. Read paths (sensors, `snapshot`) never roll the day — they
compare against today's date.

There is no user-configurable scan interval for the routed platforms: a call
is the update. Do not lower the problem sensor's poll in the hope of seeing
quota sooner; the provider does not report remaining quota at all.

