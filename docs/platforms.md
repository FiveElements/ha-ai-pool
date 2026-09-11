# Platforms

Each pool publishes exactly one entity in the matching Home Assistant domain.

## `ai_task`

Attachments are not supported. They arrive already resolved and there is no
supported way to pass a resolved attachment to another entity, so Home
Assistant rejects such calls before they reach the pool.

## `conversation`

A member answering with an error response counts as a failure, otherwise the
pool would return "sorry" from the first broken member and never reach a
working one. Languages are advertised as match-all.

## `tts`

Languages and options are the **union** across members; a member that cannot
handle a request raises and the next one is tried.

The pool entity is named explicitly (`entity.name` is the pool title). The TTS
manager refuses an engine whose name is unset.

## `stt`

Audio is buffered so a second member can be given the same recording. The
buffer defaults to 8 MB and is set in the members step of the UI (megabytes in
the form, bytes in storage).

Audio *format* capabilities are the **intersection** across members, because
the pipeline encodes once before any member is chosen. A recording larger than
the buffer is clipped to what fits and gets **one attempt with no failover**:
handing the same half-sentence to a second member cannot produce a better
transcript. The log warning says so.
