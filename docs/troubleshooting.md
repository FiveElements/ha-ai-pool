# Troubleshooting

Each topic is a symptom, then why it happens, then what to do. The pool
never hides a failure by going `unavailable`: if something cannot be
served, the call raises. The **No healthy member** problem sensor turns on
when nobody is in the preferred group; last-resort members can still serve.

## The announcement never plays / the pipeline stops

### Symptom

An automation calling the pool does nothing, or Assist answers with an
error. The pool entity itself stays available.

### Description

Every member refused or failed. The pool fires `ai_pool_exhausted`. The
**No healthy member** problem sensor may already have been on (nobody
preferred) or may still be off if last-resort members were the only ones
left. That is the intended loud failure: a declared limit is an estimate,
and a call that fails beats one that never runs.

### Resolution

1. Open the problem sensor attributes: they list each member's status.
2. Match the status:
   - `disabled` — an authentication refusal. Fix the member's API key,
     then call `ai_pool.reset_member` or reload the pool entry.
   - `exhausted` — the *declared* daily limit is spent, or the provider
     returned a quota error. Wait for local midnight, or reset with
     `clear_counters: true` if the declaration was wrong.
   - `cooldown` / `throttled` — wait, or raise the cooldown / RPM
     figures if they are too tight.
   - `unavailable` — the member integration is down.
3. Check `ai_pool_failover` events for the classified `kind` and
   `message`.

## Repair: members share a model on the same account

### Symptom

A repair issue titled "Members of {pool} share a model on the same
account".

### Description

Two entities of **one** config entry (one API key) on the same model are
the same membership listed twice. Two **accounts** on `gemini-flash-latest`
are the quota split this pool exists to provide, and do **not** raise
this repair.

### Resolution

Point the duplicates at different models, or remove one. Reload after
the options change: the repair reads live `member_model` /
`member_config_entry_id`, not a sensor cache.

## A 503 on one Google key skips the other Flash member

### Symptom

One Gemini key returns high demand and the other Flash member on a
different key is not tried.

### Description

That used to happen when a skip was keyed on the model name alone. A
capacity refusal is now per **account** (config entry) and model. The
other key must still be tried.

### Resolution

If both members share one config entry, they are one account: a 503
correctly skips the twin. Split them onto two Google config entries
(two API keys) if you meant to rotate quotas.

## Fallback rate is high

### Symptom

The Fallback rate sensor is well above zero.

### Description

A large share of today's requests needed a second member. The preference
order is working around a first choice that refuses, sits in cooldown,
or is slower than the timeout.

### Resolution

Read `failures_<kind>` on the first member's calls sensor. Change the
member order, the strategy, or fix that provider. `unknown` until the
first request of the day is not a problem.

## Latency sensors are missing

### Symptom

Only calls and fallback rate appear under the device.

### Description

Latency sensors are **disabled by default**. One measurement per member
on every success is N extra recorder series.

### Resolution

Enable the latency entity in the entity registry when you want the
chart.

## Speech-to-text transcript is truncated

### Symptom

The transcript stops mid-sentence. The log warns that audio exceeded the
retry buffer.

### Description

A recording larger than the buffer is clipped and gets **one attempt
with no failover**. Handing the same half-sentence to a second member
cannot produce a better transcript.

### Resolution

Raise the audio retry buffer in the members step (shown in MB, stored in
bytes). The default is 8 MB.

## Cannot add a second pool over the same members

### Symptom

The flow aborts with "A pool of that type already fronts exactly these
members."

### Description

Two pools over the **exact same** members each keep their own counters and
each believe they hold the whole allowance. Order is not part of the
identity. `[A, B]` and `[A, C]` are different pools; both count A.

### Resolution

Edit the existing pool (Configure → members and policy, or Reconfigure),
or pick a different member set.

## Cannot change the pool type

### Symptom

The type dropdown is missing from options / reconfigure.

### Description

Pool type decides which platform is loaded. Changing it would orphan the
published entity.

### Resolution

Create a new pool of the other type and remove the old one.

## Member still looks exhausted after midnight

### Symptom

Between midnight and the first call, a member spent yesterday still
looked exhausted.

### Description

Day counters used to roll only on the request path. They now also roll
on a local-midnight trigger, and read paths compare against
`store.today()` without mutating.

### Resolution

If a figure still looks stale, reload the entry. A restart does not
reset today's counts on purpose: a quota window does not restart with
Home Assistant.
