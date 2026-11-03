# Local Room

Local Room brings saved Persona profiles into a local, moderated group
conversation. It has its own transcript, turn-taking, and per-participant room
memory. It is a section of the **Discord Voice Bridge** addon, shown as the
**Discord Voice** tab, but a Local Room does **not** require Discord, a bot
token, or a Discord server.

The same room interface also offers a **Discord** transport. The walkthrough
below uses **Local** mode unless a step explicitly says Discord.

## Choose Local Or Discord

Open **Addons → Discord Voice → Local room**. While the room is stopped,
choose **Room transport → Local** or **Discord**. Stop the room before changing
transport.

- **Local** runs the discussion on the desktop without Discord. NC provides
  microphone, join, and room-name controls for the human participant.
- **Discord** uses your prepared Discord bots and voice channel. Each AI card
  has **Prepared bot → Choose a prepared bot…**. Complete the
  [Discord room setup](discord_voice.md) first,
  then assign the intended bot to each participant.

Both modes use **Start room**, **Continue conversation**, **Stop room**,
**Pause room**, **Resume room**, and **Room controls**. **Open conversation**
opens the corresponding **Local room** or **Discord room** source in
**Conversation**.

In Discord mode, speak and manage human membership through Discord. Typed
messages in NC use the **Send as** identity chooser: a connected human or
**NC operator**. They enter the room conversation and do not post Discord text
messages. Each participant's **Transcript** shows
delivered room speech; the individual **Memory** view and **Conversation
behavior** controls described below apply to Local mode. **Invite now** can
target bots in Discord mode.

## What It Is

- A local group conversation with a **moderator**, AI participants, and you.
- Uses saved Persona names, prompts, portraits, voice references, and optional
  per-Persona overrides.
- Can run with **Text Only**, push-to-talk, or voice activation input, but it is
  not the same runtime as Main Chat.
- Keeps room history separately from the normal Main Chat transcript.

It is not Buddy Chat (which adds buddies to Main Chat), Multi Persona Roleplay
(which has an isolated story feed), or Audio Story Mode (which follows an
imported audio or novel source).

## Setup Versus Activation

1. **Addon setup:** enable **Discord Voice Bridge** in the Addons workspace and
   restart NC if requested. Do not configure Discord credentials for a purely
   local room.
2. **Cast setup:** choose **Room transport → Local**, save your Personas, and
   add them with **+ Add Personas** or drag them from your Persona library.
3. **Room activation:** select **Start room**. If a saved discussion exists, use
   **Continue conversation** instead to restore its participant histories.
4. **Join:** choose **Join conversation** if needed, then send text or use the
   configured microphone mode.

**Start room** starts the room runtime. It does not initialize Main Chat, and
Main Chat does not run at the same time.

**Leave conversation** switches you to observing: your participant card disappears
and you are removed from the current-room roster given to the AI. You can still
watch and listen. Earlier messages remain in the conversation; choose
**Join conversation** to participate again.

## Main Chat And Local Room Are Mutually Exclusive

Only one conversation engine can run:

- **Main Chat and Local Room cannot run together, even when Main Chat is in
  Text Only mode.** Text Only disables microphone input; it does not allow both
  runtimes to coexist.
- Starting or continuing a Local Room while Main Chat is active opens a
  **Switch to Local room?** confirmation. Accepting it stops the normal chat
  engine before the room starts.
- If the main conversation has unsaved changes, NC then offers **Save**,
  **Don't Save**, and **Cancel**.
  - **Save** keeps that Main Chat for later loading.
  - **Don't Save** proceeds without saving those unsaved changes.
  - **Cancel** stops the switch. Because Main Chat was already stopped, it must
    be initialized again before normal chat can continue.
- Stop the room before initializing normal chat. NC warns that Local Room is
  active if you try to start Main Chat first.

The two conversations are separate. Starting a room does not merge or copy the
Main Chat transcript, and stopping the room does not restore Main Chat
automatically.

## Add The Cast

Use **+ Add Personas**, then **Add** beside a saved profile, or drag a Persona
into the room. Names, prompts, portraits, and voices stay linked to the Persona
profile. Edits in the shared Persona editor affect that Persona wherever it is
used.

A new room needs exactly one moderator and at least one other AI Persona to
start. The moderator is separate from your human participant and cannot be
removed directly. Other Personas can leave during a discussion, even when that
leaves only the moderator; the saved discussion can still be continued. Use
**Make moderator** to transfer the role before removing a former moderator.

You can add Personas while the room runs. A new arrival hears subsequent room
speech; it does not receive the earlier transcript as catch-up. Select a
participant for **Remove from room** or **Replace persona**. A current reply
finishes before departure/replacement completes. The arriving Persona uses its
own room memory; a replacement does not inherit the departing Persona's private
context. Check membership status and any error before trying another change.

In Local mode, click your **(you) · Joined/Observing ⋯** button, or right-click your own tile. Set **Your name in this room** and select **Save name**. The same menu contains Join/Leave, microphone mute, and Let me speak next. It remains accessible while observing.
Earlier messages keep the name recorded at the time.

## Start, Continue, And Stop

- **Start room** begins a new runtime using the configured room.
- **Continue conversation** appears when saved Local Room history exists and
  restores the room's handoff and participant histories, including after an NC
  restart.
- **Stop room** lets the current turn finish, saves the conversation and next
  speaker, then shuts down the room. In Local mode, this also unloads idle speech
  models through the Resources safety checks. Models still needed by other active
  work stay loaded. Pause and New conversation retain the speech models.
- **Pause room** lets the current speaker finish and holds the room. **Resume
  room** continues from that point.
- **Skip speech** stops the current voice and keeps the complete generated reply in the visible transcript, while the room continues. If text is still generating it finishes for display; further speech is suppressed. The complete reply counts as delivered to every participant present when you skip, just as if it had been fully vocalized. People absent from that room receive no catch-up.
- **Stop speech & hold** interrupts playback immediately and keeps the room paused until Resume.
- **New conversation** asks for confirmation because it clears **all** room
  history for that room, including participants who have been removed, plus the
  topic. It cannot be undone. Confirming then starts a fresh room (in Discord
  mode it also connects the bots). Persona profiles and voice samples are not
  deleted.

Stop an active room before switching its transport. A Local discussion and a
Discord discussion do not run as two independent rooms in this interface.

## Topic And Conversation View

Click **Edit topic…** (or **Set topic…**) beside the discussion topic, enter a focus, and select **Save topic**. **Clear topic** removes this shared focus for an open-ended conversation or brainstorming. The UI then shows **No topic set**; that label is never sent to a model. Changing or clearing the topic keeps the conversation and history. Earlier messages can still refer to an old topic. The editor also remains available through **Conversation details**.

**Open conversation** opens the discussion in the main Conversation tab with
Local room selected. Participant names and chat bubbles show the turns. Scroll
back without being pulled to the bottom, then use **Back to latest** to resume
following. Your reading position and draft are kept when you switch tabs.

While a reply is being generated, its card can show **Preparing reply…** or
**Speaking…**. When the complete text is ready, NC shows the full reply in one
card while audio continues. Conversation appearance settings control speech
highlighting and reading style. This full-text preview is display only: room
memory records delivered speech. If speech is interrupted, the card settles to
the delivered text; unheard words do not become participant memory.

## Choose Who Speaks

Select a participant or right-click its tile for quick actions:

- **Speak next** schedules a later turn.
- **Invite now** is available when the floor is free.
- **Clear next speaker** removes a queued turn.
- **Let me speak** requests a turn for you when you are joined and eligible.

The room shows **Speaking** and **UP NEXT**. A manual **Speak next** choice takes priority over automatic routing. Speaker-lock controls are hidden. **Room actions ⋯** (also available from a participant menu or by right-clicking empty room space) contains **Clear next speaker** and **Stop speech & hold**. Stop speech & hold is also directly available above the participant cards.

### Conversation behavior

In Local mode, open **Room controls → Conversation behavior** to choose:

- **NC chooses from the conversation**
- **Follow names and questions**
- **I choose each speaker**

The same selection rule covers normal turns and moderator handovers. **Let the
moderator restart the discussion** controls what happens when nobody is next.
You can set **Seconds before stepping in**, choose whether the moderator speaks
and invites someone, speaks only, or invites silently, and configure the
repeat-speaker, preparation, trigger, and cooldown options in the same dialog. It uses two columns when space permits and stacks on smaller windows. Moderator restart settings appear only when restart is enabled. **Guidance for choosing the next speaker** appears only for AI selection: it tells the selection AI what to prioritize, not what Personas should say. Leave it blank for normal rules.

Select **Save behavior**. The turn-taking settings apply only to this Local Room.

The dialog also exposes the existing Moderator controls **Allow interrupt current** (live) and **Route protected mic speech** (saved separately in addon playback settings; restart the room to apply). The first allows human speech to interrupt. With the current speaker protected, the second still transcribes and routes mic speech instead of ignoring it, without cutting off the current turn.

## Mute, Remove, And Memory

These are different actions:

- **Mute participant** makes that Persona a **listener only**. It stays in the
  room and continues to hear, but is excluded from automatic and manual speaking
  targets until unmuted. A reply already in progress finishes first.
- **Remove from room** ends the Persona's participation. Re-adding preserves its
  earlier room memory but gives no catch-up for the time it was away.
- **Mute mic** affects your microphone input, not participant routing. It is
  separate from **Mute participant**.
- **Manage participant → Make moderator** transfers the moderator role while the room is stopped. The moderator
  cannot be muted; making a muted Persona the moderator unmutes it.

Each AI participant remembers only speech **heard while present** in this Local
Room. The shared room transcript can contain turns that a participant never
heard. A returning Persona should not be expected to know what it missed.

In Local mode, open a Persona's **Memory** tab and select **Refresh** to inspect what that
participant actually retained. The configured context window can send fewer
entries than are stored. **History unavailable** is an error to retry, not proof
that memory is empty.

Saved room history that is malformed is reported instead of silently discarded.
If NC says the saved participant history is invalid, stop the room and use
**New conversation** to clear that room's saved history. Persona profiles and
voice samples are kept.

## Guidance And Speaking Aloud

Right-click a bot, or open its **⋯** menu:

- **Guide bot…** sends private direction for one reply from that bot. It answers in its own words. Guidance is not read aloud, saved as heard speech, or added as a permanent Persona prompt.
- **Speak through bot…** speaks your exact words using that bot's selected voice, without asking its language model to rewrite them.

On submit, preparation starts as soon as that bot's worker is available. The bot speaks next after the current speaker finishes. An automatic prepared handoff is replaced; the current speaker is not interrupted. Drafts stay separate for each bot and action and are kept when the dialog is cancelled. If the selected bot is itself already speaking, its current turn finishes before its worker can prepare another.

These per-bot actions are available in Local room. In Discord mode they retain the existing moderator-only directive route.

Only one directive is pending at a time. Check whether it was delivered, failed,
or cancelled before sending another.

## Persona Reply Settings

Select a linked participant and inspect **Reply settings**. Open **Settings and
sources** for its effective language model, context limit, and Document Memory
package and the source of each setting. **Edit
Persona overrides** opens the shared editor from inside the room. **Save
overrides** changes that Persona wherever it is used and applies to new
requests; the current reply keeps its captured settings.

A missing or unready document package warns and contributes no excerpts. The
room itself still keeps its own conversation history.

## Anonymous room mode

**Your room menu → Anonymous participants** (or **Room controls → Room anonymity** in Discord mode) hides human/AI role labels in subsequent model
requests. Earlier messages can still reveal identities. Start a new conversation
only if you want a clean experiment; the switch does not erase history or hide
identities from Discord itself.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Local room tab/section is missing | Enable **Discord Voice Bridge** and restart NC if requested |
| Start room asks to switch | Main Chat is still active; review the switch and unsaved-chat prompts |
| No AI replies | Confirm the room is running, the cast has a moderator and another Persona, and NC's chat provider is ready |
| No microphone input | Check **Join conversation**, **Mute mic**, and the **Session setup** input mode. Text still works |
| A Persona will not speak | It may be muted, removed, waiting for its turn, or excluded by the speaker rule |
| A removed Persona forgot events | Its room memory only contains speech heard while present; there is no catch-up |
| Saved room history is invalid | NC reports it rather than discarding it. Stop the room and use **New conversation** to clear that room's saved history |
| Voice does not match the Persona | Check the linked voice sample and whether the active TTS backend supports reference audio |
| New conversation cleared everything | That action intentionally clears all histories and the topic for this room, then starts a fresh room |

## Current Limits

- Main Chat and Local Room are separate, mutually exclusive runtimes.
- **Text Only** removes microphone input but does not make the two runtimes
  compatible.
- Local Room uses NC's current chat and speech providers. It is not an offline
  model or a Discord-only feature.
- Distinct character voices require valid samples and a compatible
  reference-capable TTS backend.
- Participant memory is heard-only and has no catch-up. The shared transcript is
  not the same thing as an individual participant's memory.
- New conversation is destructive and intentionally clears removed
  participants' history too.

## Related Guides

- [Discord room and bot accounts](discord_voice.md)
- [Buddy Chat](buddy_chat.md)
- [Multi Persona Roleplay](roleplay.md)
- [Audio Story Mode](audio_story_mode.md)
- [Addon setup and index](../manual/addons.md)

## Keeping the room visible

Local room starts with compact information above the participants. **More info** beside the topic expands the saved-history and turn-taking summaries; **Workspace info** beside the section tabs shows the Discord Voice introduction and search. These are display choices and do not change room settings. Wide layouts fit four participant cards across. Participant details scroll inside their sidebar, keeping the room in place. Right-clicking your own card opens your controls at the click position; the top identity button remains available while observing.


## Settings updates

Discord Voice keeps addon settings and each bot's generated configuration in memory. Room and Moderator status refreshes do not reread those settings files. Saving a setting updates the desktop's memory after the save succeeds; running bots receive the existing reload or cast-change command when a live change applies. Settings that already require restarting the room retain that behavior.

Edits made directly to `settings.local.json` outside NC are imported when you use **Apply Global Live Settings** or restart NC. Routine status updates do not scan that file for changes. The settings schema is loaded once per application session. Chat history and live room status keep their existing persistence and delivery behavior.
