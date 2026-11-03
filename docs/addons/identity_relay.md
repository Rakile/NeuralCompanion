# NC Identity Relay

**NC Identity Relay** stores identity-continuity artifacts imported from an
external LLM session and can associate one of them with a Persona. It is
**experimental**. Importing, selecting, or reviewing an artifact is not the same
as activating it in a conversation.

Identity Relay is not [User Identity](user_identity.md). User Identity describes
the human user. Identity Relay carries imported assistant continuity. It is also
not a backup of a chat history, a Persona copy, or a voice/avatar generator.

## What It Does

- Provides a protocol you can give to an external LLM session.
- Imports the resulting `NC_IDENTITY_EXPORT` JSON or text without rewriting it.
- Preserves the raw artifact and shows a best-effort structured extraction.
- Supports an explicit connection review for one Persona.
- Keeps continuity off until you enable it for the current conversation.

Imported text is **source material**, not trusted instructions. It may be
incomplete, contradictory, or simply wrong about the source session. Read it
before using it.

## Setup Versus Activation

Open **Addons → NC Identity Relay** to reach this workspace.

1. **Addon setup:** enable **NC Identity Relay** in the Addons workspace and
   restart NC if requested.
2. **Import:** create an export, then import the artifact.
3. **Inspect:** review the raw artifact, structured extraction, and mechanical
   warnings.
4. **Associate:** in **Persona → Identity Relay**, choose an imported identity.
5. **Review:** select **Review identity**, choose the identity subject, and
   review every item.
6. **Activate:** apply the review, then enable **Identity Relay** in the Chat
   window for that conversation.

Selection alone does not activate continuity. **Connected** means the Persona is
associated and reviewed; the Chat switch still controls whether the continuity
is active for the current conversation.

## Create An Export

Open **Create Identity Export**:

- **View Export Protocol** shows the complete protocol.
- **Copy Export Protocol** copies it.

Send that complete protocol to the external LLM session you want to export from.
The source model can only derive what it can honestly see in its available
conversation and memory. A richer source history can produce a richer artifact,
but the result is still a model-generated representation.

Review the returned `NC_IDENTITY_EXPORT` artifact before importing it. Copying
the protocol does not contact the external provider or create an export by
itself.

## Import An Artifact

Open **Import**:

1. Enter a descriptive **Source label**, for example `Writing partner - October`.
2. Paste the complete artifact into **Pasted NC_IDENTITY_EXPORT artifact** and
   select **Import Pasted Artifact**, or use **Import From File** for a `.json`
   or `.txt` file.
3. Inspect the returned selection and any validation warnings.

A successful import only stores the artifact. It does not approve it for
conversation use or attach it to a Persona.

## Inspect Stored Artifacts

Open **Stored Artifacts** and select an item. Compare:

- **Raw Artifact** — the preserved source.
- **Structured Extraction** — NC's best-effort interpretation.
- **Mechanical Warnings** — validation and parsing issues.

Check names, relationships, and provenance against the original. **Re-run
Extraction** recalculates the structured view. **Delete Artifact** removes the
stored artifact; disconnect a Persona first if you are unsure what still refers
to it.

### Identity subject

The review requires an **Identity subject**. This is NC's interpretation of whose
continuity the artifact represents, not a claim that the source is authentic.
Choose the correct subject when the review asks; do not approve an ambiguous
artifact merely to finish the dialog.

## Privacy And Provider Exposure

Open **Privacy** to review **Owner Override: allow selected records to external
providers**.

By default, selected identity records are not automatically exposed to external
providers. Enabling Owner Override requires confirmation and removes that
provider-exposure barrier for records selected for a turn. Relevance, capacity,
provenance, malformed-data, and quarantine checks still apply.

Owner Override is **not required** to import, inspect, or simply store an
artifact. Review the provider you intend to use and the sensitivity of the source
before enabling it. For a local provider, the same review discipline still
applies.

## Associate And Review Through Persona

Open **Persona → Identity Relay**. The card can show:

- **Not used by this persona**
- **Review pending**
- **Needs review**
- **Connected**

Choose an **Imported identity** from the selector, then wait for **Preparing
review...**. When **Review identity** appears, open the review dialog.

The review dialog shows **Review imported identity**, the **Identity subject**
selector, and a **Review item** card for each group NC still needs you to decide.
One review item can cover several extracted records when they share the same
decision. For each item, choose an allowed **Decision**:

- **Approve**
- **Reclassify**, with a **Reclassification** choice
- **Narrow Use**, with an **Allowed runtime use** scope
- **Quarantine**

Not every action is available for every item. Review the evidence; **Show
advanced evidence and transparency** exposes source paths, record IDs, policy
narrowing, and attestation state.

If **Transient continuity** records are present, they are inactive by default.
**Activate reviewed transient continuity for this session** applies only to the
current chat session and still requires the review to be applied.

Select **Apply review** only when the subject and every item are intentional.
**Cancel** leaves the previous state unchanged. A pending review blocks another
selection until it is resolved or cancelled.

## Enable It In Conversation

After the Persona review is connected, open **Chat**. The **Identity Relay**
switch appears in the conversation header when the feature is available:

- **On** — imported persona continuity is active for this conversation.
- **Off** — the connection is retained but suspended.

The switch is per conversation. Do not assume that enabling it once makes every
new chat use the same identity. Check the header state before relying on
continuity.

To disconnect, use the Persona Identity Relay card's disconnect action and
confirm the review. Disconnecting does not delete the imported artifact.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Import succeeds but the Persona cannot use it | Import is not association. Choose it in **Persona → Identity Relay** and complete **Review identity** |
| The Persona shows **Needs review** | A review is pending, blocked, or no longer current. Reopen **Review identity** |
| The Chat switch is missing | Confirm the addon is available, the Persona is associated, and the review is connected |
| The relay is connected but not active | Turn on the **Identity Relay** switch in the conversation header |
| Review cannot be submitted | Choose the identity subject and make a decision for every review item |
| Provider exposure is blocked | Review **Privacy → Owner Override** and the provider you intend to use; do not enable it casually |
| The imported text disagrees with the source | Treat the artifact as model-generated source material, inspect the raw view, and re-import a corrected export if needed |
| The review is rejected | Read the stated reason, recheck provenance and capacity, and do not repeatedly resubmit an invalid artifact |

## Current Limits

- Identity Relay is experimental. Its review contract, extraction, and provider
  behavior may change.
- Imported content is not verified truth and is not trusted instructions.
- Structured extraction is best effort; the raw artifact remains the source of
  record.
- A connected Persona still depends on relevance, capacity, provenance,
  quarantine, and policy checks at request time.
- Continuity can be blocked or omitted even when the artifact is connected.
- The Chat switch controls the current conversation; it is not a global
  always-on identity setting.
- Identity Relay does not create a voice, avatar, image, or complete copy of the
  source conversation.
- Owner Override is a privacy-sensitive action. It removes one exposure barrier;
  it does not bypass every safety or data-quality check.

## Related Guides

- [User Identity](user_identity.md)
- [Voice Studio](voice_studio.md)
- [Addon setup and index](../manual/addons.md)
