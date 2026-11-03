export type VisualReplyBaseline = {
  cacheKey: string;
  updatedAt: number;
};

type VisualReplyState = {
  image_url_path?: unknown;
  image_cache_key?: unknown;
  updated_at?: unknown;
};

type VisualReplyContainer = {
  state?: VisualReplyState;
};

function finiteTimestamp(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

export function captureVisualReplyBaseline(visual: VisualReplyContainer | undefined): VisualReplyBaseline {
  return {
    cacheKey: String(visual?.state?.image_cache_key || ''),
    updatedAt: finiteTimestamp(visual?.state?.updated_at),
  };
}

export function isFreshVisualReply(
  baseline: VisualReplyBaseline,
  state: VisualReplyState | undefined,
): boolean {
  if (!String(state?.image_url_path || '').trim()) {
    return false;
  }
  const cacheKey = String(state?.image_cache_key || '');
  const updatedAt = finiteTimestamp(state?.updated_at);
  if (updatedAt > baseline.updatedAt) {
    return true;
  }
  return Boolean(cacheKey) && cacheKey !== baseline.cacheKey && updatedAt >= baseline.updatedAt;
}
