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

Languages, options and voices are the **union** across members; a member that
cannot handle a request raises and the next one is tried.

Voices are what the Assist pipeline editor lists under the TTS engine, so a
pool of Gemini entities offers the same voice picker as one Gemini entity. A
voice appears once even when several accounts list it. The chosen voice is
passed unchanged to whichever member answers: in a pool mixing providers, a
voice one provider does not know makes that member fail and the next is tried.
The pool sets no default voice of its own; with none chosen, each member uses
its own default.

The pool entity is named *Text-to-speech* under the pool's device, so a new
pool's entity id is `tts.<pool>_text_to_speech`. The other pool types take the
device's name, but the TTS manager refuses an engine whose `entity.name` is
None. Pools created before this change keep their entity id.

## `stt`

Audio is buffered so a second member can be given the same recording. The
buffer defaults to 8 MB and is set in the members step of the UI (megabytes in
the form, bytes in storage).

Audio *format* capabilities are the **intersection** across members, because
the pipeline encodes once before any member is chosen. A recording larger than
the buffer is clipped to what fits and gets **one attempt with no failover**:
handing the same half-sentence to a second member cannot produce a better
transcript. The log warning says so.
