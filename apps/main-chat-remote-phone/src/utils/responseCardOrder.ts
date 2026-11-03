export const DEFAULT_RESPONSE_CARD_ORDER = [
  'continuous', 'selected', 'controls', 'story', 'microphone', 'engine', 'reset', 'session',
] as const;

export type ResponseCardId = typeof DEFAULT_RESPONSE_CARD_ORDER[number];

export function normalizeResponseCardOrder(value: unknown): ResponseCardId[] {
  const known = new Set<string>(DEFAULT_RESPONSE_CARD_ORDER);
  const saved = Array.isArray(value) ? value.filter((id): id is ResponseCardId => typeof id === 'string' && known.has(id)) : [];
  const order = [...new Set(saved), ...DEFAULT_RESPONSE_CARD_ORDER.filter(id => !saved.includes(id))];
  if (!saved.includes('story') && saved.includes('session')) {
    order.splice(order.indexOf('story'), 1);
    order.splice(order.indexOf('session'), 0, 'story');
  }
  return order;
}

export function moveResponseCard(order: readonly ResponseCardId[], from: ResponseCardId, to: ResponseCardId, after = false): ResponseCardId[] {
  if (from === to || !order.includes(from) || !order.includes(to)) return [...order];
  const next = order.filter(id => id !== from);
  next.splice(next.indexOf(to) + (after ? 1 : 0), 0, from);
  return next;
}
