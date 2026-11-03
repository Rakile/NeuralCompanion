# Discord Voice and Discord rooms

**Discord Voice Bridge** connects saved NC Personas to bot accounts in a Discord
voice channel. Open **Addons → Discord Voice**. For the shared room interface,
open **Local room** and choose **Room transport → Discord** while stopped.
**Local** mode uses the desktop instead; see [Local Room](local_room.md).

Room conversations have their own transcript and Persona memory. They use NC's
configured chat, STT and TTS providers without adding turns to Main Chat. Prepare
the providers using [Chat and speech](../manual/chat-and-tts.md) before starting.
Main Chat and a room cannot run together, including when Main Chat is Text Only.
Starting a room can prompt to stop Main Chat and save its unsaved conversation.
Stopping the room does not restart Main Chat automatically.

## Prepare Discord accounts

Each simultaneous AI participant needs a different Discord **bot account**.
A Persona is the character; an account is the Discord connection it uses. Create
bot applications in Discord's Developer Portal, obtain their bot tokens, and
invite every bot to the server before trying to start the room.

For the target voice channel, each bot needs **View Channel**, **Connect** and
**Speak**. Allow **Change Nickname** for the Persona name to appear as its server
nickname. Channel permission overrides can still block a bot that has a server
role. Enable Developer Mode in the Discord client to copy the server and voice
channel IDs. You need permission to install/invite bots to that server.

### Invite each bot to the server

In the Discord Developer Portal, open that bot's application and choose
**Installation**. Enable **Guild Install**. Under **Default Install Settings →
Guild Install**, include the **bot** scope and select **View Channel**, **Connect**,
**Speak**, and **Change Nickname**. Copy the **Install Link**, open it in a browser,
choose **Add to server**, and authorize it for your server. Repeat for every bot
account. **User Install** or the **applications.commands** scope alone does not
add a voice bot to the server. Check channel overrides if the installed bot
still cannot connect. See [Discord's installation walkthrough](https://docs.discord.com/developers/quick-start/getting-started)
and [permission reference](https://docs.discord.com/developers/topics/permissions).

### Add accounts in NC

On NC's **Discord** setup section:

1. In **Bot accounts**, select **Add account**.
2. Enter the **Bot token** and, optionally, an **Account label**. An empty label
   receives a name such as Bot1. This label identifies the reusable account in NC.
3. Select **Add account**. Saving adds the account and checks its token against
   Discord. Wait for the account list and notification result.
4. Repeat for the other accounts. **Check all accounts** checks saved tokens again
   and updates their Discord names, avatars and verification results.
5. Enter the shared **Server ID** and **Voice channel ID** for the room.

**Edit → Save changes** also checks the account. Leave its token blank to keep
the saved token. Tokens are write-only in the UI and saved in ignored local
addon settings; keep them out of screenshots and support reports. Existing
advanced environment-variable credentials remain supported, but the normal room
workflow uses **Bot accounts**.

**Bot token verified** confirms the token belongs to a bot. It does not invite
that bot, join a voice channel, prove voice permissions, or test the NC providers.
An invalid result needs a replacement token; an unavailable or rate-limited
check can be retried later. An account in use can have editing/removal blocked;
read the reason shown on its card.

The Discord transport needs Node.js/npm and the bundled Node bridge dependencies.
Use **Install / Update Node Deps** if validation reports them missing;
stop running bridges before changing those dependencies. NC launches and stops
its bridge processes. Normal room use does not require separate `npm start` or
TinyMVP terminal windows. Standalone development instructions are in the
[technical bridge README](../../addons/discord_voice_bridge/README.md).

## Build and start the room

1. Save the characters you want in the Persona addon.
2. Open **Local room**, choose **Discord**, then **+ Add Personas** or drag saved
   Personas into the room. A new room requires one moderator and at
   least one other AI Persona to start.
3. Use **Prepared bot** on each Persona card to assign a different prepared
   account. Choose **Make moderator** on the intended moderator before starting.
   Each account can serve only one room participant at a time.
4. Review names, voices and the shared server/channel. Select **Start room**, or
   **Continue conversation** when saved room history is available. Allow the
   connections and startup checks to finish; use **Resume room** if held/paused.
5. Join that voice channel in Discord and speak there. NC displays connected
   human participants from Discord alongside the Personas.

NC attempts to set each bot's **server nickname** to its Persona name. It does
not rename the bot's global Discord account. The account list reports the server
nickname and any failure. A missing Change Nickname permission, invalid name or
name over Discord's 32-character limit can prevent the update. Fix the reported
issue and reconnect; changing an NC account label is not a Persona rename.

**Open conversation** opens **Conversation → Discord room**. The workspace and
conversation view share the room state, transcript and typed draft. Stopping the
room saves its delivered history and continuation state. **New conversation** is
a separate, confirmed reset; stop the Discord room first. It starts fresh room
history and topic without deleting Persona profiles or voice samples.

Saved Discord room state is checkpointed per server and voice channel. If that
checkpoint is corrupt or does not match this room's identity, NC reports the
error and preserves the existing file; it does not silently begin a fresh
history or overwrite it. Stop the room, read the error, and use **New
conversation** only if you intend to replace that saved checkpoint.

## Humans and typed input

Use Discord for microphone, playback and channel membership. The desktop's
Local-mode **Join conversation**, **Mute mic** and **Let me speak** controls do
not control your Discord client. Human names come from Discord membership, with
Discord display-name/username fallback when a guild nickname is unavailable.

In NC's room composer, **Send as** selects a connected human or **NC operator**.
With one human present NC can select that human initially; with several, choose
explicitly. Selecting a participant for moderation is a separate action and does
not change the sender. If the saved sender disconnects, sending is blocked until
you select an available sender. NC does not silently attribute the draft to
someone else.

**Send** enters typed input into the NC room context with that identity. It does
not send a Discord text-channel message or post as that Discord user. Bot replies
still use Discord voice. Use **Room controls → Say it aloud** when you want the
moderator to speak the draft to the room. Sending is unavailable while paused.

## Decide whose voice is accepted

In Discord setup, **Accept incoming voice from** offers:

- **Everyone**: accepts incoming voice regardless of the ID list.
- **Listed users**: uses **Discord user IDs (optional)**, separated by commas,
  spaces or semicolons. **An empty list also accepts everyone.** It does not
  block all voice.

Select **Save Settings** and restart the bridge/room to apply changed voice-acceptance
settings. Acceptance only determines whose incoming voice can enter processing;
turn routing, mute state, filtering and current-speaker protection can still
prevent a reply. These controls do not change Discord server permissions.

## Turn-taking and moderator guidance

Select or right-click a participant:

- **Speak next** queues the selected bot or human after the current speaker.
  For a human, speak through Discord when the floor is yours.
- **Invite now** calls a bot when the floor is free. It is not available for
  human participants.
- **Only this speaker** holds the floor until **Release speaker lock**.
- **Clear next speaker** clears the queued selection.
- **Mute routing / Unmute routing** changes NC's routing eligibility. It does
  not change Discord server mute. The room moderator stays unmuted.

A manual next-speaker choice replaces an automatic pending handoff. If you select
the bot that is already speaking, the pending next choice is cleared; it is not
a request to repeat the current turn. Watch **Speaking** and **UP NEXT** rather
than treating a queued choice as an immediate interruption.

In **Room controls**, **Guide conversation** sends private, temporary direction
to the moderator. The moderator replies after the current speaker; guidance
replaces an automatic prepared handoff rather than cutting off current speech.
**Say it aloud** speaks the draft publicly. Wait for a pending directive to
finish, fail or cancel before submitting another. Guidance is not a permanent
Persona prompt or a public typed user message.

**Pause room** finishes the current speaker and holds the room. **Resume room**
continues. **Stop speech & hold** interrupts playback immediately and holds the
floor. **Stop room** waits for the current turn and history settlement before
saving and shutting down; if it reports a speaker that will not finish, use
**Stop speech & hold**, then retry.

The **Moderator** section also provides detailed speaker controls and
**Allow interrupt current**. With the current speaker protected, microphone
speech does not steal the floor. **Route protected mic speech** allows accepted
human microphone speech to be transcribed and routed into context while that
protection remains in force; it does not authorize interruption. This is
separate from incoming-voice acceptance. Optional Discord server-mute enforcement
in Moderator is a separate explicit feature and needs appropriate Discord mute
permissions; a room's routing-mute button alone does not enable it.

## Add, remove, replace, or move a participant

You can use **+ Add Personas** while a room runs. A new Discord arrival needs a
free prepared account; the chooser can select an available one automatically or
you can choose one explicitly. If none is free, add an account in Discord setup
or wait for the departing account's cleanup to complete.

Select a participant for **Remove from room**, **Replace persona**, or a change
of **Prepared bot** where enabled. A current reply finishes before the departure
or replacement completes. Wait for the membership status to settle. A failed
join offers **Retry join**; read its error before retrying. The live moderator
keeps its account and cannot be removed directly. It can be replaced on that
account; stop the room to transfer the moderator role to another participant.
Other Personas may leave until only the moderator remains, and that saved
discussion can still be continued. Actions are disabled during incompatible startup, shutdown or
membership operations.

Memory belongs to the Persona's room participation, not to the reusable bot
account. New arrivals receive no transcript catch-up for time away. A returning
Persona can use its own earlier room memory, including on a different account.
A replacement does not inherit the previous Persona's private context. Speech
already in progress is heard according to who was present for that turn; joining
mid-turn does not grant its earlier content.

## Transcript, full reply display, and memory

The Conversation view can show **Preparing reply…** or **Speaking…** while a
reply is generated. Once the complete text is ready, it appears as one card
while playback continues. Conversation appearance settings control speech
highlighting and reading style. The full-text display is a temporary preview,
not evidence that every word has been heard.

The saved room transcript and model history contain confirmed delivered speech.
After interruption, the card settles to delivered text, and unheard words do
not become room memory. A participant's **Transcript → Refresh** displays that
shared delivered Discord transcript; it is not an inspector of that Persona's
private model context. Persona memory still respects presence and has no
catch-up for missed turns. Local mode instead offers a per-participant **Memory**
inspector and its own **Conversation behavior** controls.

**Reply settings → Settings and sources** shows a linked Persona's effective
provider/model, context and document recall. **Edit Persona overrides** changes
the saved Persona wherever it is used; changes affect new requests and leave
the current reply's captured settings intact.

**Room controls → Anonymous** hides human/AI role labels from subsequent model
requests. Earlier history may reveal identities. It does not anonymize Discord
accounts, server membership or the visible Discord client.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Token verified but bot cannot join | Invite that bot to the correct server; check shared IDs and voice-channel permission overrides |
| Wrong displayed bot name | Check Persona name, Change Nickname permission, nickname error and account assignment |
| No account available for a new Persona | Wait for cleanup or add another prepared account |
| Connected human gets no reply | Check incoming-voice IDs, routing mute, current-speaker protection, filters and the next-speaker choice |
| Typed input is disabled | Resume the room and choose an available **Send as** identity |
| Saved Discord room is reported corrupt | NC preserves the checkpoint instead of overwriting it. Stop the room, read the error, and use **New conversation** only if you intend to replace it |
| Voice works but distinct characters sound alike | Check each Persona's voice sample and a reference-capable active TTS backend |
| Full reply was visible but memory is shorter | Only delivered speech is committed; a preview may include words that were interrupted |
| Returning Persona does not know a missed event | No catch-up is performed for time away |

See [Local Room](local_room.md) for the desktop microphone, participant Memory
view and Local-only behavior settings, and [addon setup](../manual/addons.md)
for enabling addons.
