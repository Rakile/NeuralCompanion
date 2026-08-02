# Audio Story Bounded Memory and Batched Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep only the selected and next Audio Story chapters resident while analyzing story prompts in small sequential LLM batches with compact continuity context.

**Architecture:** Add two focused addon-local helpers: one for token/character-bounded story-analysis batches and one for a capacity-two chapter working set. Keep storage backward-compatible by adding a chapter-scoped restore API, then adapt the controller to load, install, prefetch, evict, and play chapter payloads asynchronously. Existing whole-project work will stream persisted chapters and install only the selected chapter.

**Tech Stack:** Python 3, PySide6, standard-library dataclasses/collections/threading, existing Audio Story project store/checkpoints, existing smoke-test harnesses.

## Global Constraints

- Change files only under `addons/audio_story_mode`.
- Do not change project manifests, checkpoint schemas, provider APIs, core runtime files, dependencies, presets, remotes, or other addons.
- Never block the Qt GUI thread.
- Existing saved projects must open without migration or destructive writes.
- Keep at most two owned chapter artifact payloads: selected/current and next.
- Use no more than eight image chunks and 12,000 serialized input characters per analysis batch.
- Keep every final serialized LLM user prompt below 24,000 characters.
- Compact context is capped at 12 characters, 8 locations, 8 props, and 4 recent scenes.
- Use a 180-second provider timeout per batch.
- Failed batches use heuristic results locally and do not discard successful batches.
- Do not commit or push unless the user explicitly requests it.

---

### Task 1: Pure bounded story-analysis batches

**Files:**
- Create: `addons/audio_story_mode/analysis_batches.py`
- Modify: `addons/audio_story_mode/smoke_audio_story_workflow.py`

**Interfaces:**
- Produces: `ContinuityContextLimits`, `StoryAnalysisBatch`, `partition_analysis_chunks(...)`, `compact_continuity_context(...)`, and `bounded_story_prompt_payload(...)`.
- Consumes: plain mappings and sequences only; this module must not import Qt, controller, provider, or project-store code.

- [ ] **Step 1: Add failing partition and context-cap smoke tests**

Add focused tests that construct 19 chunks and a Story Bible with 801
characters, then assert:

```python
batches = partition_analysis_chunks(chunks)
assert [len(batch.chunks) for batch in batches] == [8, 8, 3]
assert all(batch.serialized_input_characters <= 12_000 for batch in batches)

context = compact_continuity_context(memory, batches[0].chunks)
assert len(context["characters"]) <= 12
assert len(context["locations"]) <= 8
assert len(context["props"]) <= 8
assert len(context["recent_scenes"]) <= 4
assert "character_eric" in context["characters"]
```

Also assert deterministic ordering by recent-use index, confidence, and stable
ID, and assert inputs are not mutated.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -c "from addons.audio_story_mode import smoke_audio_story_workflow as s; s.test_story_analysis_batches_are_bounded(); s.test_compact_continuity_context_is_relevant_and_capped()"
```

Expected: import failure because `analysis_batches.py` does not exist.

- [ ] **Step 3: Implement immutable batch construction**

Create:

```python
@dataclass(frozen=True)
class ContinuityContextLimits:
    characters: int = 12
    locations: int = 8
    props: int = 8
    recent_scenes: int = 4


@dataclass(frozen=True)
class StoryAnalysisBatch:
    batch_index: int
    chunk_start_index: int
    chunks: tuple[dict[str, object], ...]
    serialized_input_characters: int
```

Implement:

```python
def partition_analysis_chunks(
    image_chunks: Sequence[Mapping[str, object]],
    *,
    max_chunks: int = 8,
    input_character_budget: int = 12_000,
) -> tuple[StoryAnalysisBatch, ...]:
```

Copy each chunk once, preserve order and original `chunk_index`, and close a
batch before adding a chunk that would exceed either bound. Truncate a single
oversized chunk excerpt so every batch still satisfies the budget.

- [ ] **Step 4: Implement relevant compact continuity selection**

Implement:

```python
def compact_continuity_context(
    memory: Mapping[str, object],
    batch_chunks: Sequence[Mapping[str, object]],
    *,
    limits: ContinuityContextLimits = ContinuityContextLimits(),
) -> dict[str, object]:
```

Match stable IDs, labels, display names, and aliases case-insensitively against
batch text and recent-scene references. Select matches first, then fill
remaining slots by `last_seen_chunk` descending, confidence descending, and
stable ID ascending. Copy style fields and only the last four recent scenes.

- [ ] **Step 5: Implement final prompt bounding**

Implement:

```python
def bounded_story_prompt_payload(
    *,
    batch: StoryAnalysisBatch,
    continuity_context: Mapping[str, object],
    story_style_guide: str,
    continuity_strength: float,
    max_serialized_characters: int = 24_000,
) -> dict[str, object]:
```

Serialize with `ensure_ascii=False` to measure the exact payload. Reduce chunk
excerpt lengths before dropping non-referenced fallback entities. Raise
`ValueError` only if the fixed schema/style portion alone exceeds the cap.

- [ ] **Step 6: Run focused and workflow smoke tests**

Run:

```powershell
python -c "from addons.audio_story_mode import smoke_audio_story_workflow as s; s.test_story_analysis_batches_are_bounded(); s.test_compact_continuity_context_is_relevant_and_capped(); s.test_story_analysis_prompt_payload_is_below_limit()"
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: all tests pass.

- [ ] **Step 7: Review checkpoint**

Run:

```powershell
git diff --check -- addons/audio_story_mode/analysis_batches.py addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: no output.

### Task 2: Sequential provider batches and per-batch fallback

**Files:**
- Modify: `addons/audio_story_mode/controller.py`
- Modify: `addons/audio_story_mode/smoke_audio_story_workflow.py`
- Consume: `addons/audio_story_mode/analysis_batches.py`

**Interfaces:**
- Consumes: Task 1 batch/context helpers.
- Produces: `_build_batched_llm_story_analysis(...) -> dict`, returning
  `{"story_bible": dict, "scenes": list, "batch_stats": dict}`.

- [ ] **Step 1: Add failing sequential-call tests**

Add controller-harness tests with 19 chunks and a fake provider. Assert exactly
three ordered calls, no concurrent calls, prompt length below 24,000
characters, original chunk indices retained, and progress text containing
`batch 2 of 3`.

- [ ] **Step 2: Add failing timeout/fallback/cancellation tests**

Use fake provider outcomes `success`, `TimeoutError`, `success`. Assert the
middle eight chunks use heuristic scenes, batch three still runs, and stats
equal:

```python
{"total": 3, "llm": 2, "heuristic": 1}
```

Add a cancellation token test that cancels after batch one and asserts no
second call or cache publication.

- [ ] **Step 3: Run focused tests and verify RED**

Run the new functions directly with `python -c`; expected failure is missing
`_build_batched_llm_story_analysis`.

- [ ] **Step 4: Implement sequential batch orchestration**

Replace the single whole-chapter call inside `_build_story_payload` with
`_build_batched_llm_story_analysis`. For each batch:

1. Build compact context from the current in-job Story Bible.
2. Build the bounded payload.
3. Emit `Analyzing <chapter> - batch N of M...`.
4. Call instructor or normal analysis once.
5. Normalize results against only that batch's chunks.
6. Merge Story Bible updates before constructing the next batch.
7. Offset returned local batch indices to the original chunk indices.

Keep all state local to the worker until the owning job is validated.

- [ ] **Step 5: Remove the nested whole-analysis daemon timeout**

Do not call `_build_llm_story_analysis_with_timeout` from the batched path.
Create one `JobDeadline(timeout_seconds=180.0)` for each provider call and set
the request timeout to the remaining batch deadline. Retain only compatibility
retries that remove a provider-rejected optional parameter.

- [ ] **Step 6: Implement batch-local heuristic fallback and reporting**

Catch provider/parse/timeout failures around one batch, sanitize and emit the
specific message, build heuristic scenes only for that batch, and continue.
Expose successful/fallback counts in final progress without changing the
persisted checkpoint schema.

- [ ] **Step 7: Run focused and full workflow tests**

Run:

```powershell
python addons/audio_story_mode/smoke_audio_story_workflow.py
python -m py_compile addons/audio_story_mode/analysis_batches.py addons/audio_story_mode/controller.py
```

Expected: all tests pass and compile succeeds.

- [ ] **Step 8: Review checkpoint**

Run `git diff --check` for the three Task 1/2 files. Expected: no output.

### Task 3: Chapter-scoped restore and capacity-two working set

**Files:**
- Create: `addons/audio_story_mode/chapter_working_set.py`
- Modify: `addons/audio_story_mode/project_restore.py`
- Modify: `addons/audio_story_mode/smoke_audio_story_projects.py`

**Interfaces:**
- Produces: `ChapterWorkingSet`, `ChapterCacheKey`, and
  `project_restore.load_chapter_artifacts(store, project, chapter_id)`.
- Preserves: `load_project_artifacts(...)` for compatibility tests and legacy
  callers.

- [ ] **Step 1: Add failing single-chapter restore tests**

Use an instrumented fake store and three completed chapters. Assert
`load_chapter_artifacts(..., "chapter-2")` performs exactly two document loads
for chapter 2, calculates the global audio offset from manifest durations, and
never reads chapters 1 or 3.

- [ ] **Step 2: Add failing working-set tests**

Assert:

```python
cache = ChapterWorkingSet(capacity=2)
cache.put(key1, payload1, protected_chapter_id="chapter-1")
cache.put(key2, payload2, protected_chapter_id="chapter-1")
cache.put(key3, payload3, protected_chapter_id="chapter-1")
assert cache.get(key1) is payload1
assert cache.get(key2) is None
assert cache.get(key3) is payload3
assert len(cache) == 2
```

Also test project/revision invalidation and ownership return without deepcopy.

- [ ] **Step 3: Run focused tests and verify RED**

Run the new project smoke functions directly; expected failures are missing
API/module symbols.

- [ ] **Step 4: Implement `load_chapter_artifacts`**

Validate project/chapter identity, reject archived or unknown chapters,
calculate the chapter's global offset from preceding active manifest
durations, and reuse `_load_stage_document` for exact checkpoint/fingerprint
validation. Return one `RestoredChapterArtifacts` plus issues in a
`ProjectArtifactRestore` containing a one-item tuple.

- [ ] **Step 5: Implement the working set**

Use `OrderedDict[ChapterCacheKey, object]`. `put` moves the inserted key to the
most-recent end and evicts the oldest key whose chapter ID is not protected.
`invalidate(project_id, manifest_revision)` removes entries not matching both
values. `clear()` releases all owned payload references.

- [ ] **Step 6: Run project smoke and compile tests**

Run:

```powershell
python addons/audio_story_mode/smoke_audio_story_projects.py
python -m py_compile addons/audio_story_mode/chapter_working_set.py addons/audio_story_mode/project_restore.py
```

Expected: all tests pass.

### Task 4: Lazy project open, selection, and next-chapter preload

**Files:**
- Modify: `addons/audio_story_mode/controller.py`
- Modify: `addons/audio_story_mode/smoke_audio_story_projects.py`
- Modify: `addons/audio_story_mode/smoke_audio_story_workflow.py`
- Consume: Task 3 helper modules.

**Interfaces:**
- Produces controller methods
  `_request_story_project_chapter(chapter_id: str, *, reason: str, resume_position: float | None = None) -> None`,
  `_install_prepared_story_chapter(result: Mapping[str, object]) -> bool`, and
  `_prefetch_next_story_project_chapter(chapter_id: str) -> None`.

- [ ] **Step 1: Add failing project-open ownership test**

Instrument the store while opening a 21-chapter project. Assert project open
does not call `load_project_artifacts`, loads only the first active chapter,
and owns no more than two payloads after next-chapter prefetch completes.

- [ ] **Step 2: Add failing rapid-selection and transcript-view tests**

Complete chapter B's worker after chapter C was selected. Assert B is rejected,
C installs, and the transcript editor contains C text but not A/B text.

- [ ] **Step 3: Run focused tests and verify RED**

Run the new smoke functions directly; expected failure is eager all-project
restore or absent request methods.

- [ ] **Step 4: Make project open lightweight**

Change `_open_story_project_from_session` and `_open_story_project` workers to
prepare the manifest, audio descriptors, image-path metadata, and summary
without loading chapter documents. After `_refresh_story_project_ui` selects
the first/retained chapter, request that chapter asynchronously.

- [ ] **Step 5: Wire chapter selection with stale-result ownership**

Replace the chapter list's direct refresh connection with a slot that refreshes
controls and advances a chapter-load generation. Validate project ID, manifest
revision, selected chapter ID, and generation before installation.

- [ ] **Step 6: Install one chapter without copies**

Adapt `_assemble_project_restore_payload` to accept the one-chapter restore.
Install with ownership transfer, display chapter-relative transcript
paragraphs incrementally, keep timestamps globally offset, and update the
summary/status with the selected chapter name.

- [ ] **Step 7: Prefetch and evict**

After valid installation, locate the next non-archived chapter and run a
background worker if it is not cached. Do not install a prefetch result into
Qt. Insert it into `ChapterWorkingSet`, protecting the selected chapter.

- [ ] **Step 8: Stream project-wide analysis completion**

Change `_build_project_story_payload` so it persists each chapter result and
releases that chapter's transcript/analysis objects before continuing. Return
a small completion descriptor containing selected chapter ID, final manifest
revision, batch statistics, and audio summary. Reload/install only the selected
chapter after transcription or staged planner application completes.

- [ ] **Step 9: Run project/workflow tests**

Run both smoke scripts and `py_compile controller.py`. Expected: all pass.

### Task 5: Playback-boundary loading and safe recovery

**Files:**
- Modify: `addons/audio_story_mode/controller.py`
- Modify: `addons/audio_story_mode/smoke_audio_story_workflow.py`
- Test: `addons/audio_story_mode/smoke_audio_story_tts_queue.py`

**Interfaces:**
- Produces `_chapter_id_for_global_position(position_seconds)`,
  `_ensure_story_chapter_ready_for_position(position_seconds)`, and a single
  pending resume record owned by the current project/generation.

- [ ] **Step 1: Add failing prefetched-transition test**

With chapter 1 active and chapter 2 cached, move playback across the boundary.
Assert chapter 2 installs synchronously from cache, the media position remains
global, and playback does not pause.

- [ ] **Step 2: Add failing unloaded-transition and error tests**

With chapter 2 uncached, assert playback pauses, emits
`Loading next chapter`, requests chapter 2 once, and resumes only after a
current valid result. A corrupt result must keep the project open, leave
playback paused, and show a chapter-specific error.

- [ ] **Step 3: Implement position-to-chapter lookup**

Use `imported_audio_sources` global start/end values and active chapter order.
Do not inspect transcript data to locate a chapter.

- [ ] **Step 4: Gate visual/playback synchronization**

Before synchronizing a chunk at a new source boundary, require the matching
chapter payload. Install cached payloads immediately. Otherwise store the
desired global position and prior playing state, pause, and use Task 4's
chapter request API.

- [ ] **Step 5: Resume safely**

After valid installation, restore the requested global position, resume only
if playback was previously active, clear the pending record, and prefetch the
following chapter. Clear pending resumes on stop, project switch, shutdown, or
generation invalidation.

- [ ] **Step 6: Run playback, TTS, workflow, and project suites**

Run:

```powershell
python addons/audio_story_mode/smoke_audio_story_tts_queue.py
python addons/audio_story_mode/smoke_audio_story_workflow.py
python addons/audio_story_mode/smoke_audio_story_projects.py
```

Expected: all tests pass.

### Task 6: Full verification, memory measurement, and runtime synchronization

**Files:**
- Modify only failing Audio Story test files if verification exposes an
  addon-local regression.
- Copy the final changed Audio Story files to
  `Q:\new new new\NeuralCompanion-dev-worktree\addons\audio_story_mode`.

**Interfaces:**
- Consumes all previous tasks.
- Produces verification evidence and the synchronized runtime patch.

- [ ] **Step 1: Run all Audio Story smoke suites**

Run all four `smoke_audio_story_*.py` scripts. Expected: zero failures.

- [ ] **Step 2: Compile every changed Python file**

Run `python -m py_compile` with the explicit changed file list. Expected: exit
code 0.

- [ ] **Step 3: Re-run the 21-chapter diagnostic**

Open the inspected runtime project through the new chapter-scoped preparation
path under `tracemalloc`. Assert owned artifact keys contain only selected and
next chapters and compare live/peak allocations to the recorded 62.5/66.7 MiB
all-artifact baseline.

- [ ] **Step 4: Check scope and whitespace**

Run:

```powershell
git diff --check
git status --short
git diff --name-only
```

Confirm every newly changed implementation file is below
`addons/audio_story_mode` and preserve pre-existing unrelated work.

- [ ] **Step 5: Synchronize only approved addon files**

Resolve and verify both absolute addon roots. Copy only the explicit changed
Audio Story file list from the clean tree to the runtime tree. Do not copy
repository-wide files and do not alter the runtime's existing MuseTalk or
preset changes.

- [ ] **Step 6: Verify the runtime copy**

Run `py_compile` and all four Audio Story smoke suites from
`Q:\new new new\NeuralCompanion-dev-worktree`. Compare every synchronized file
with `git diff --no-index` or SHA-256 hashes.

- [ ] **Step 7: Final review**

Report changed files, measured before/after ownership, tests, remaining risks,
runtime synchronization, and manual validation:

1. Restart the dev runtime.
2. Open the 21-chapter project and watch RAM settle.
3. Switch chapters rapidly.
4. Play across a chapter boundary.
5. Re-run story analysis through LM Studio and confirm bounded batch progress.

Do not commit or push without a separate explicit user request.
