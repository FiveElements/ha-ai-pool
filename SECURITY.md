# Security policy

## Supported versions

Only the latest release receives fixes. HACS offers it as an update as soon as
it is tagged.

## Reporting a vulnerability

Please report privately through
[GitHub private vulnerability reporting](https://github.com/FiveElements/ha-ai-pool/security/advisories/new),
not in a public issue.

Expect an acknowledgement within a week. Once a fix is released the advisory is
published with credit, unless you ask otherwise.

## Scope

The pool holds no credentials and opens no connection of its own: every call goes
through the provider entities it fronts. Reports about those providers belong to
their own integrations. In scope here: anything that lets the pool call an entity
it was not configured with, leaks prompts or results into events, logs or
diagnostics, or corrupts its stored counters.
