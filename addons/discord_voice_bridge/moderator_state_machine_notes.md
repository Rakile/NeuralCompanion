# Discord Voice Bridge Moderator State

This addon treats moderation as a single floor-control state machine.

## Authoritative State

- Current bot: `current_bot_id`, `current_bot_name`, `current_bot_discord_user_id`, `current_bot_turn_id`.
- Current human: `current_human_route`, `current_speaker_user_id`, `current_speaker_name`.
- Next bot: `pending_route.target_bot_id`. `route_next_target_bot_id` is only a compatibility mirror and must not resurrect a cleared Next by itself.
- Next human: `pending_human_route.speaker_user_id` / `speaker_name`. `route_next_speaker_user_id` / `route_next_speaker_name` are only compatibility mirrors and must not resurrect a cleared Next by themselves.
- Persistent speaker locks: `floor_target_bot_id` for bots and `floor_speaker_user_id` / `floor_speaker_name` for humans.
- Mutes and only-speaker locks: `muted_bot_ids`, `muted_speaker_user_ids`, and `only_bot_ids`.
- Dead-air bookkeeping: `dead_air_recovery.last_next_target_bot_id` is status only and must be cleared when pending speaker state is cleared.
- Manual command invalidation uses `last_command_at_ms`. Do not use the file-wide `updated_at_ms` as a command timestamp, because status/route-flow writes also update it.

## Rules

- Exactly one participant should be Current, or none when the room is quiet.
- Exactly one participant should be Next, or none when automatic routing is allowed.
- Human and bot Next are mutually exclusive.
- All moderator state writes pass through a normalizer that keeps mirror fields aligned with authoritative state objects and clears impossible Current/Next combinations.
- Bot Current is authoritative only when `current_bot_id` is set; names, Discord user ids, and turn ids are cleared with it and are display metadata only.
- Bot Current must resolve to a live moderator target. Stale ids such as `default` are cleared and must not block a pending human from becoming Current.
- Bot Next must also resolve to a live moderator target. Stale ids such as `default` are cleared and must not block dead-air recovery or automatic routing.
- Selecting a bot as Next while a human is Current must preserve Current human but clear any old human Next.
- Selecting a human as Next stores `pending_human_route`; that pending human is the only accepted human speaker until they speak or Pending is cleared.
- Room-router candidates include routable humans as `human:<participant_id>` alongside bot ids. The LLM router chooses one target id; bot targets generate/prebuffer replies, while human targets set the human floor.
- Manual moderator Next overrides LLM routing and dead-air recovery.
- Routed work derived from a human moderator decision is marked as manual state, so later router/dead-air decisions cannot overwrite it while it is pending.
- Only pending routes with `user_command: true` are treated as fresh moderator UI commands for completed-text republish. Prepared routed work must not retrigger its own manual republish loop.
- Dead-air recovery must not queue the selected Moderator bot while that bot is muted or excluded by floor-control state, and control reasons such as `moderator_muted` must not be converted into human-floor routes.
- Generic no-route reasons such as `human-to-human room talk`, `room talk`, or `not a specific bot` must not automatically queue the only human in the room. Human-floor fallback requires an explicit human name/id or a stronger direct-human reason.
- Router/dead-air writes must not overwrite a manual bot or human Next.
- Prebuffered routed turns are valid only while they still match the current moderator state. If any Next changes, human Next is selected, or Clear Pending happens before playback starts, stale prepared chunks and queued audio must be dropped.
- Muting a pending/locked participant clears that pending/lock state and invalidates stale prepared work for that participant.
- Routed text turns validate their target against authoritative state before generation starts, so a routed file picked up just before Clear Pending cannot become a phantom Current.
- Stale routed payload invalidation compares moderator/human-intervention markers against the route start timestamp, not only payload creation time. A route that started before Clear Pending/manual Next must not survive by writing its file after the command.
- Routed text files become visible only after `pending_route` is marked for the same target and route key. If the file write fails, that matching pending route is rolled back.
- Room route result files become visible only after the accepted turn has been broadcast into shared bot histories and appended to room context.
- Completed-turn routing has separate in-flight and published states. In-flight suppresses duplicate route attempts while the route decision is running; published is set only after the route decision file is written, so failures before publication can retry.
- A claimed reply floor protects a routed turn only after that turn is actively playing as Current.
- Completed bot/moderator speech must be routed and broadcast to shared bot histories before Current is cleared, the reply floor is released, and the next participant is allowed to start.
- If completed-turn routing starts early for prepare-ahead, playback completion must await that same routing promise before handoff.
- If completed-turn routing returns no target while the completed speaker still owns Current, eligible dead-air recovery may queue/prebuffer the moderator as Next immediately, but playback still waits until Current is cleared.
- When the dead-air Moderator speaks and calls a next participant, the next participant may be queued/prebuffered as soon as the Moderator reply text is complete, but playback still waits until the Moderator floor is released.
- Dead-air Moderator next-prebuffer may only start after the Moderator turn has claimed the reply floor. A completed-but-not-yet-playing Moderator reply must not let the next participant skip ahead of the Moderator.
- `Clear Pending` clears Next only. It must not stop an active Current speaker; use Stop Speech / Clear Current for that.
- `Clear All` clears Current, Next, speaker locks, dead-air next status, routed text files, and all tracked stale prebuffer state.

## Reader / Writer Map

- All moderator state writes go through `writeModeratorState()` / `updateModeratorState()`, which normalize Current/Next before persisting.
- Manual command writers live in `handleModeratorCommand()`: route-next, human route-next, give-floor, mute/only locks, clear-pending, clear-floor, and clear-all.
- Runtime floor writers are `markBotCurrentForTurn()`, playback-start state updates, `clearCurrentBotModeratorState()`, `setHumanCurrentFromRoute()`, `promotePendingHumanRouteToCurrent()`, `consumeModeratorPendingRoute()`, and `consumeModeratorPendingHumanRoute()`.
- Routed/prebuffer writers use `markModeratorPendingBotRoute()` through `writeRoutedTextTurn()`. Human-moderator routed work must be marked manual.
- Dead-air writes only status in `dead_air_recovery.last_next_target_bot_id` until it queues an actual routed text turn.
- Current/Next readers are `moderatorDecisionForTurn()`, `routedTextWriteBlockedByManualNext()`, `moderatorPendingBotRouteBlockReason()`, `routedTurnModeratorStateInvalidationReason()`, `maybeQueueDeadAirRecovery()`, `isRoomQuietForRecovery()`, mute enforcement, and the Qt controller status tables.
