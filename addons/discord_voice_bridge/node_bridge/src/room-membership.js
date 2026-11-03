function matches(member, identity) {
  return Boolean(member && identity && ['bot_id', 'participant_id', 'admission_id']
    .every(key => typeof identity[key] === 'string' && identity[key] && member[key] === identity[key]));
}

export function roomMemberForIdentity(roster, identity) {
  if (!Array.isArray(roster?.members)) return null;
  const members = roster.members.filter(member => matches(member, identity));
  return members.length === 1 ? members[0] : null;
}

export function acceptRoomRoster(previous, incoming) {
  if (incoming?.version !== 1 || !Number.isInteger(incoming.revision) || incoming.revision < 0
      || !Array.isArray(incoming.members) || incoming.members.some(member => !member ||
        !['joining', 'ready', 'leaving', 'left', 'failed'].includes(member.phase)
        || ['bot_id', 'participant_id', 'admission_id'].some(key => typeof member[key] !== 'string' || !member[key]))) return null;
  if (previous && incoming.revision < previous.revision) return null;
  // Reusing a revision with different identities is not a new acknowledgment.
  if (previous && incoming.revision === previous.revision
      && JSON.stringify(incoming) !== JSON.stringify(previous)) return null;
  const present = incoming.members.filter(member => member.phase !== 'left');
  for (const key of ['bot_id', 'participant_id', 'admission_id']) {
    if (new Set(present.map(member => member[key])).size !== present.length) return null;
  }
  return incoming;
}

export function roomMemberMayProceed(roster, identity, purpose, turnId = '') {
  if (!identity) return roster == null; // Standalone bridges retain existing behavior.
  const member = roomMemberForIdentity(roster, identity);
  if (!member) return false;
  if (member.phase === 'ready') return ['route', 'prepare', 'playback', 'drain', 'history'].includes(purpose);
  return member.phase === 'leaving' && ['playback', 'drain', 'history'].includes(purpose)
    && Boolean(turnId && member.drain_turn_id && String(turnId) === member.drain_turn_id);
}

// A listener receives a complete chunk only when the same admission spans it.
export function roomHearingAudience(roster) {
  return (roster?.members || []).filter(member => member.phase === 'ready')
    .map(({participant_id, admission_id}) => ({participant_id, admission_id}));
}

export function roomAudienceIncludes(audience, identity) {
  return Boolean(identity && Array.isArray(audience) && audience.some(member =>
    member.participant_id === identity.participant_id && member.admission_id === identity.admission_id));
}

export function roomDeliveryAudience(startAudience, endRoster) {
  const current = roomHearingAudience(endRoster);
  return (Array.isArray(startAudience) ? startAudience : []).filter(member => roomAudienceIncludes(current, member))
    .map(({participant_id, admission_id}) => ({participant_id, admission_id}));
}

export function roomSpeakerMayProceed(roster, payload) {
  if (!payload?.speaker_bot_id && !payload?.speaker_is_bot) return true;
  const identity = {bot_id: payload.speaker_bot_id, participant_id: payload.speaker_participant_id,
    admission_id: payload.speaker_admission_id};
  const member = roomMemberForIdentity(roster, identity);
  return Boolean(member && member.persona_id === payload.speaker_persona_id
    && roomMemberMayProceed(roster, identity, 'history', payload.speaker_turn_id));
}

export function roomPreviewMayProceed(roster, pending, target) {
  if (!pending || !target || pending.target_bot_id !== target.bot_id
    || pending.target_participant_id !== target.participant_id || pending.target_admission_id !== target.admission_id
    || !roomMemberMayProceed(roster, target, 'prepare')
    || !roomAudienceIncludes(pending.source_audience_admissions, target)) return false;
  const source = {bot_id: pending.source_bot_id, participant_id: pending.source_participant_id,
    admission_id: pending.source_admission_id};
  return roomMemberMayProceed(roster, source, 'history', pending.source_turn_id);
}
