# Delete a message in PC normal chat

Each user and assistant message has a trash-can **Delete** action, including
image-only messages. It opens a confirmation with a preview. Cancel changes
nothing. In the current UI, deletion also reconciles memories attributable to
that message; there is no separate memory-cleanup checkbox. Untraceable memories,
shared image assets, later replies, and original image files are preserved.
Deletion requires current generation, playback, and conflicting edits to finish.

Save the chat afterward to update its saved copy. Previously saved copies,
exports and backups are not erased. There is no new undo command.

For current step-by-step instructions, see [Edit or delete history](manual/conversation.md#edit-or-delete-history)
and [Memory](manual/memory.md).

## Memory choice

**Also remove associated long-term memories** starts checked each time.

- Checked: remove records and archived chunks with a reliable source range
  overlapping the selected message, their embeddings, and associated asset links.
  Invalidate the combined continuity summary so future updates use retained chat
  content. A mixed chunk/record can contain other messages too; that derived item
  is invalidated as a unit. Unrelated records/chunks are preserved.
- Unchecked: preserve learned content, embeddings and the continuity summary.
  Detach overlapping positional provenance so a later deletion cannot mistake
  it for the message that shifted into that position.
- Preserve unknown provenance and report it. Preserve shared image assets and
  report those reached by this cleanup. Original disk files are never deleted.
  Unreadable retained attachments conservatively protect stored image assets.

This is not secure erasure or a guarantee of forgetting. Information repeated
in retained replies, untraceable memories, shared images or old saved copies can
still be recalled. Invalidated derived chunks are not immediately regenerated
by a model as part of deletion.

## Safety and recovery

Deletion checks the message ID, conversation revision and session, and rejects
stale confirmations. It is unavailable during generation, queued/active speech
or conflicting chat editing. Existing short session effects drain before memory
cleanup. A new memory epoch prevents old extraction, archive, image-refresh,
embedding and summary jobs from writing deleted information back afterward.

SQLite cleanup is transactional. Summary replacement is reversible separately;
this is not a cross-storage atomic transaction. On storage failure, canonical
history stays unchanged. If rollback/restoration fails, the error explains that
memory recovery is required. That session's memory work stays suspended until
the same deletion is retried successfully with memory cleanup checked. Do not
switch chats or restart to bypass a recovery warning; inspect the store if the
retry also fails. Abrupt process termination/power loss between storage changes
is not covered by a durable recovery journal.

## Implementation scope

- `core/memory_message_deletion.py`: scoped database/summary cleanup.
- `core/runtime/{memory,memory_embeddings,production_memory}.py`: stale-write
  exclusion, recovery, retained-image protection.
- `core/runtime/{conversation,production_session,turns,facade}.py` and production
  composition bindings: canonical deletion and busy/identity checks.
- `ui/qml_bridge/application_bridge.py`, Conversation QML and action layout/defaults:
  trash icon, confirmation, default checkbox, feedback and existing-layout migration.
- Focused deletion smoke modules plus updated action-layout expectations.

No phone/gateway code, NC engine/audio behavior, dependency versions, database
schema or original image files were changed. Runtime mirroring is recorded below.

