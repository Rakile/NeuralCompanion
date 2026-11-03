// Room hold state helper for the Discord voice bridge.
//
// A hold is either draining (one exact bot/turn may proceed) or paused (nobody
// may proceed). Holds are only removed by resumeRoom; completed holds stay in
// the paused phase so another requester cannot take over the room early.

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function cloneValue(value) {
  if (Array.isArray(value)) {
    return [...value];
  }
  return isObject(value) ? { ...value } : value;
}

function cloneState(state) {
  const next = isObject(state) ? { ...state } : {};
  if (Object.prototype.hasOwnProperty.call(next, "room_hold")) {
    next.room_hold = cloneValue(next.room_hold);
  }
  return next;
}

function nonEmptyId(value) {
  return typeof value === "string" && value.trim() !== "" ? value : "";
}

function isHoldShape(hold) {
  return Boolean(
    isObject(hold)
    && typeof hold.request_id === "string"
    && (hold.phase === "draining" || hold.phase === "paused")
    && typeof hold.drain_bot_id === "string"
    && typeof hold.drain_turn_id === "string"
  );
}

function isDrainingHold(hold) {
  return Boolean(
    isHoldShape(hold)
    && hold.phase === "draining"
    && hold.drain_bot_id.trim() !== ""
    && hold.drain_turn_id.trim() !== ""
  );
}

export function requestRoomHold(state, currentTurn = {}) {
  const next = cloneState(state);
  if (next.room_hold != null) {
    return next;
  }

  const turn = isObject(currentTurn) ? currentTurn : {};
  const botId = nonEmptyId(turn.bot_id);
  const turnId = nonEmptyId(turn.turn_id);
  const completePair = botId !== "" && turnId !== "";
  next.room_hold = {
    request_id: typeof turn.request_id === "string" ? turn.request_id : "",
    phase: completePair ? "draining" : "paused",
    drain_bot_id: completePair ? botId : "",
    drain_turn_id: completePair ? turnId : ""
  };
  return next;
}

export function roomTurnMayProceed(state, botId, turnId) {
  const hold = isObject(state) ? state.room_hold : null;
  if (hold == null) {
    return true;
  }
  if (!isDrainingHold(hold)) {
    return false;
  }
  if (typeof botId !== "string" || typeof turnId !== "string") {
    return false;
  }
  if (botId.trim() === "" || turnId.trim() === "") {
    return false;
  }
  return botId === hold.drain_bot_id && turnId === hold.drain_turn_id;
}

export function completeRoomHold(state, activity = {}) {
  const next = cloneState(state);
  const hold = next.room_hold;
  if (!isDrainingHold(hold)) {
    return next;
  }

  const event = isObject(activity) ? activity : {};
  if (event.bot_id !== hold.drain_bot_id || event.turn_id !== hold.drain_turn_id) {
    return next;
  }
  if (
    event.generation_complete !== true
    || event.audio_drained !== true
    || event.routing_settled !== true
  ) {
    return next;
  }

  next.room_hold = { ...hold, phase: "paused" };
  return next;
}

export function resumeRoom(state) {
  const next = cloneState(state);
  delete next.room_hold;
  return next;
}
