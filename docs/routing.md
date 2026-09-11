# Routing

Declared limits only **reorder** members. Exhausted, cooling or throttled
members are still tried as a last resort. A wrong guess about a quota must not
become a silent no-op. The one exception is `disabled` (authentication).

## Two accounts on the same model

Two API keys on `gemini-flash-latest` are two daily counters, which is the
point of a pool. Two entities of **one** account on that model are the same
membership listed twice: they share a quota and fail together.

The pool reads each member's model *and* the provider config entry that owns
it — the subentry first, for providers that publish several entities per
account. It raises a **repair** only when members share a model *and* an
account.

!!! note "A 503 is this key's view"

    A `429 RESOURCE_EXHAUSTED` / quota message is your limit. A bare `429 Too
    Many Requests` or a `503 UNAVAILABLE` / high demand is this key being told
    the model is busy. Another account on the same
    model is still worth asking. The pool only skips other members of **the
    same account** on that model for the rest of *this* request. A skip is
    not charged as an attempt.

Providers name the model option as they please and are free to change it, so
this is a heuristic: an unreadable model is reported as `null` and carries no
conclusion, never a false match.

## Rate limits you can actually measure

Providers meter three dimensions: requests per minute, input **tokens** per
minute, and requests per day. Token counts are not available — Home Assistant
returns the result, never the provider's usage report. Characters are what can
honestly be measured.

**`calls_today` and `requests_today` bracket the truth.** A provider charges a
request when it receives it, but a server-error refusal probably costs nothing.
`calls_today` counts successes, `requests_today` counts every attempt. Routing
uses the optimistic one.

Google applies limits **per project, not per API key**, so two accounts really
do get independent allowances. Specified rate limits are not guaranteed:
a member can refuse while well inside its declared limit.

## Giving up on a member

Each attempt has a deadline, **120 seconds** by default, configurable per pool
and disabled with `0`. Past it the member is abandoned and the next one is
tried. A deadline never reorders members; it only stops one from holding a
request open forever. Timeouts are their own failure kind.

## Cooldowns that lengthen

Capacity refusals arrive in clusters, so each consecutive refusal doubles the
member's cooldown, up to an hour. Only a **success** resets it. Cooldown is per
**member**, not per model.

A refusal that names a spent allowance is read as quota even when it arrives as
`403`. Authentication is the one verdict that stops a member from being tried
again, so evidence of a quota outranks a bare status code.

Reloading the entry re-admits every disabled member. The `ai_pool.reset_member`
service clears cooldown, the spent-allowance mark and the disable — see
[Observability](observability.md).
