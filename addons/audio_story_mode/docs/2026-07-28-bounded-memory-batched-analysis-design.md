# Audio Story Bounded Memory and Batched Analysis Design

Date: 2026-07-28

## Status

Implemented and verified in the Audio Story addon on 2026-07-28.

## Scope

This change is limited to `addons/audio_story_mode`. It addresses:

1. Excessive RAM use when opening saved multi-chapter projects.
2. Oversized LLM story-analysis requests and fixed whole-analysis timeouts.
3. Unclear progress while chapters and LLM analysis batches are processed.

It must preserve existing project files, checkpoints, audio playback, image
generation, staged settings, TTS, casting, and provider selection.

## Evidence and Root Cause

The inspected runtime project contains 21 active chapters:

- Saved analysis documents: approximately 28.3 MiB.
- Saved transcript documents: approximately 2.4 MiB.
- Current artifact restoration: approximately 62.5 MiB of live traced Python
  allocations and approximately 66.7 MiB peak.
- Current combined restore payload: approximately 76 MiB before the Qt
  transcript document and media backend are included.

Project open currently loads every active chapter's transcript and analysis.
It then builds combined raw segments, transcript chunks, scene plans, full
text, formatted transcript paragraphs, anchors, and Story Bible data.

Each saved analysis also repeats substantial transcript and continuity data.
The inspected project Story Bible is approximately 445 KiB and contains 801
character entries. The complete Story Bible is copied into LLM prompt input,
so limiting transcript samples alone does not bound the request.

The existing 120-second wrapper covers the complete chapter analysis. It uses
a nested daemon thread, so the caller can fall back while a provider request
is still finishing in the background.

## Considered Approaches

### 1. Increase the timeout only

This is the smallest code change, but it leaves eager project loading,
oversized continuity input, and abandoned provider work unchanged. Rejected.

### 2. Normalize and migrate every saved project document

Separating transcripts, scene data, and project continuity into a new storage
schema would reduce disk duplication. It introduces migration, checkpoint,
rollback, and compatibility risk. Rejected for this patch.

### 3. Bounded chapter working set and bounded LLM batches

Load only the selected chapter and its successor. Stream any project-wide work
one chapter at a time. Analyze one small LLM batch at a time with compact,
relevant continuity context. This fixes the active RAM and request-size
problems without rewriting saved projects. Approved.

## Architecture

### Lightweight project state

Opening a project loads only:

- The normalized project manifest.
- Chapter order and archived state.
- Audio paths, durations, and global audio offsets.
- Checkpoint status and small image-path metadata already held by the
  manifest.

Project open must not call the existing all-chapter artifact restoration path.
That path remains available for compatibility while addon callers move to the
chapter-scoped loader.

### Chapter artifact loader

An addon-local chapter loader reads and validates the checkpoint-pinned
transcript and analysis for one chapter. It returns an owned chapter payload
with:

- Chapter identity and manifest revision.
- Global audio offset.
- Raw transcript segments.
- Transcript and image timing chunks.
- Scene plan and relevant anchors.
- Story/style metadata required to render and play that chapter.
- User-safe artifact issues.

Global audio timestamps are calculated when the chapter payload is prepared.
Collections inside the payload remain chapter-local; they are not combined
with every other chapter.

### Two-chapter working set

The controller owns a capacity-two working set keyed by project ID, manifest
revision, and chapter ID:

- The selected or currently playing chapter is protected from eviction.
- Its next active chapter is prefetched.
- Any older, unprotected payload is released when the capacity is exceeded.
- Opening another project or changing the manifest revision invalidates the
  complete working set.

The working set owns payloads without further deep copies. Qt installation
uses the same ownership-transfer pattern as the prepared project-open path.

### Asynchronous chapter selection

Selecting a chapter:

1. Advances a chapter-load generation token.
2. Installs a matching cached payload immediately, or starts an addon worker.
3. Shows `Loading <chapter name>...` in the Audio Story operation status.
4. Discards a completed worker result if the project, manifest revision,
   chapter selection, or generation token changed.
5. Installs the valid result and then preloads the next active chapter.

The transcript panel displays only the selected chapter. It continues using
incremental Qt text batches so a large single chapter does not freeze repaint.

### Playback transition

Audio-source metadata remains global and lightweight. At a chapter boundary:

- If the next chapter is prefetched, the controller installs it and continues.
- If it is not ready, playback pauses, reports
  `Loading next chapter: <name>...`, loads it on a worker, and resumes from the
  requested global audio position.
- Seeking to an unloaded chapter follows the same load-and-resume path.
- Failure to load a chapter leaves the project open and playback paused with a
  chapter-specific error.

### Project-wide operations

Operations that require multiple chapters must iterate checkpoint-pinned
chapter documents sequentially and release each large document before loading
the next. They may retain compact accumulated results such as identifiers,
status counts, timing offsets, or the committed Story Bible. They must not
materialize all transcript and analysis documents simultaneously.

## Batched LLM Analysis

### Batch construction

Image-timing chunks are processed in original order. A batch is closed when
either limit would be exceeded:

- Eight image chunks.
- A 12,000-character serialized batch-input budget for chunk excerpts and
  compact continuity context.

The content budget is measured before the provider call. It includes the
selected chunk excerpts and compact continuity context. The implementation
must keep the serialized user prompt below 24,000 characters so the prompt
plus an output allowance remains suitable for common local 8k-token contexts.

### Compact continuity context

The complete committed Story Bible is never inserted into a batch request.
Instead, an addon-local selector provides:

- Project style, palette, world, and negative-style rules.
- At most four recent scene summaries.
- Entities explicitly referenced by batch text or recent scene identifiers.
- A bounded fallback set sorted by most recent use, then confidence, then
  stable entity ID.
- No more than 12 characters, 8 locations, and 8 props.

Stable entity IDs are preserved. The full committed Story Bible remains the
authoritative project continuity store; the compact object is only a provider
request view.

### Sequential merge

Only one provider batch may be active for a chapter:

1. Build the compact context for the next batch.
2. Call the selected provider.
3. Normalize the returned scenes and Story Bible update.
4. Merge the update into the in-job continuity state.
5. Use that updated state when preparing the next batch.
6. Merge all normalized batch scenes back into original chunk order.

Missing scene results are filled by the existing heuristic scene builder.
Batch boundaries must not create duplicate scenes or reset stable IDs.

### Timeout and cancellation

Each provider batch receives a 180-second provider timeout and matching
deadline. The analysis already runs on an Audio Story background worker, so
the nested daemon timeout thread is removed from the batched path.

Cancellation is checked:

- Before building a batch.
- Before and after the provider call.
- Before merging or saving the result.

No later batch starts until the prior provider call has returned or raised.
Provider compatibility retries remain limited to removing an explicitly
unsupported request parameter; a timeout does not launch duplicate retries.

### Batch failure

If a batch times out or fails:

- Log the provider label, batch number, and sanitized specific error.
- Build heuristic results for only that batch.
- Continue with later batches.
- Preserve successful earlier batch results.

The final chapter checkpoint can complete with mixed LLM and heuristic scene
sources. The UI reports the number of successful and fallback batches.

## Operation Status

Audio Story uses the existing compact operation-status bar. New messages
include:

- `Opening project index...`
- `Loading chapter 3 of 21: Chapter 2...`
- `Preloading next chapter: Chapter 3...`
- `Analyzing Chapter 2 - batch 2 of 7...`
- `Chapter 2 analysis complete - 6 LLM batches, 1 heuristic fallback.`
- `Loading next chapter for playback...`

Status animation and color behavior remain Audio Story-only.

## Compatibility and Data Safety

- Existing project manifests and chapter documents remain readable.
- No automatic destructive migration or deletion occurs.
- Checkpoint fingerprints continue to validate exact stored revisions.
- Invalid current-chapter artifacts produce a local issue and do not prevent
  the project manifest from opening.
- Invalid prefetched artifacts are reported only when selected or needed for
  playback.
- No provider, runtime-core, or addon-framework API changes are required.

## Tests

### Chapter working-set tests

- Opening a 21-chapter project does not load 21 transcript/analysis pairs.
- The cache never owns more than two chapter payloads.
- The selected/current chapter cannot be evicted.
- Switching rapidly rejects stale worker results.
- A manifest revision or project change invalidates cached payloads.
- Transcript display contains only the selected chapter.
- Current-to-next playback transitions use a prefetched payload.
- Missing prefetch pauses safely, loads, and resumes at the correct position.
- Corrupt or missing current/next artifacts fail without closing the project.

### LLM batching tests

- More than eight chunks produce multiple ordered calls.
- Every serialized user prompt remains below 24,000 characters.
- A Story Bible with hundreds of entities is reduced to the stated caps.
- Relevant stable entity IDs survive between batches.
- Batch results merge into original chunk order without duplicates.
- A timed-out batch uses heuristic results and later batches continue.
- Cancellation prevents subsequent calls and prevents stale saves.
- Provider compatibility fallback does not duplicate successful calls.
- Progress includes chapter name and batch position.

### Regression and measurement

- Existing project, workflow, settings-workload, and TTS smoke suites pass.
- Existing saved projects open without schema conversion.
- Whole-project playback, TTS, casting, image lookup, and staged setting
  application retain their behavior.
- A diagnostic fixture with 21 chapters confirms that live artifact ownership
  is bounded by the selected and next chapter rather than total chapter count.

## Files Expected to Change

The implementation plan may refine exact names, but changes must remain
addon-local and are expected in:

- `addons/audio_story_mode/project_restore.py`
- `addons/audio_story_mode/controller.py`
- A small addon-local chapter-working-set module.
- A small addon-local LLM batching/continuity-context module.
- Existing Audio Story smoke-test files.

Core runtime files, shared addon framework files, presets, dependencies,
remotes, and other addons are explicitly out of scope.

## Acceptance Criteria

1. Opening a project retains at most selected and next chapter artifact
   payloads.
2. The transcript UI shows the selected chapter only.
3. Playback preloads and transitions to the next chapter without blocking the
   UI thread.
4. LLM story analysis uses sequential bounded batches and compact context.
5. Each batch has a 180-second provider timeout and a prompt below 24,000
   characters.
6. One failed batch falls back locally without discarding successful batches.
7. Existing saved projects require no migration.
8. The patch changes only Audio Story addon files and passes its regression
   suites.
