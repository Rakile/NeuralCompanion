export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object');
}

export function remoteActionError(payload: unknown, fallback = 'Remote command failed.'): string {
  if (!isRecord(payload)) {
    return '';
  }
  if (payload.ok === false) {
    return String(payload.error || fallback);
  }
  if (payload.accepted === false) {
    return String(payload.message || payload.error || fallback);
  }
  const result = payload.result;
  if (isRecord(result)) {
    if (result.ok === false) {
      return String(result.error || fallback);
    }
    if (result.accepted === false) {
      return String(result.message || result.error || fallback);
    }
    const sendResult = result.send_result;
    if (isRecord(sendResult) && sendResult.accepted === false) {
      return String(sendResult.message || sendResult.error || 'Transcript was created but main chat did not accept it.');
    }
  }
  return '';
}
