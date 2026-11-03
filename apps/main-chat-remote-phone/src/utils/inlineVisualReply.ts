import type { InlineVisualReply } from '../api/types.ts';

function timestamp(value: number | string | null | undefined): number {
  const numeric = Number(value);
  if (Number.isFinite(numeric)) return numeric;
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed / 1000 : 0;
}

export function orderedVisualReplies(items: readonly InlineVisualReply[]): InlineVisualReply[] {
  return [...items];
}

export function visualReplyPresentation(item: InlineVisualReply): {
  kind: 'progress' | 'image' | 'error';
  label: string;
} {
  if (item.status === 'generating') {
    return { kind: 'progress', label: 'Creating Visual Reply…' };
  }
  if (item.status === 'ready' && (item.url_path || item.content_type === 'image/demo')) {
    return { kind: 'image', label: item.caption || 'Visual Reply' };
  }
  return { kind: 'error', label: item.error || 'Visual Reply unavailable.' };
}

export function shouldEmergeVisualReply(
  item: InlineVisualReply | null | undefined,
  dismissedIds: ReadonlySet<string>,
  sessionStartedAt: number,
): boolean {
  return Boolean(
    item
    && item.status === 'ready'
    && item.id
    && !dismissedIds.has(item.id)
    && timestamp(item.updated_at ?? item.created_at) >= sessionStartedAt,
  );
}
