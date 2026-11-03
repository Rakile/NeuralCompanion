// Only fixed validation messages may cross the private character error boundary.
const validation = new Set([
  'Enter a portrait prompt under 5001 characters.',
  'Unknown portrait style.',
  'Maximum characters must be a whole number from 1 to 20.',
  'Configure and check this voice-design provider in Voice Studio first.',
  'The saved voice is unavailable. Refresh the voice library.',
  'Two character generations are already pending. Wait for them to finish.',
  'That name already belongs to another character in this conversation.',
]);
export function characterRequestError(status: number, raw: string): string {
  if (validation.has(raw)) return raw;
  if (status === 409) return 'This character changed. Refresh or discard your draft, then try again.';
  if (status === 503) return 'Chat characters are unavailable. Check that NC desktop and the required addon are running.';
  if (status === 401) return 'Reconnect to NC desktop before editing characters.';
  return `Character request could not be completed (HTTP ${status}). Refresh the card and try again.`;
}
