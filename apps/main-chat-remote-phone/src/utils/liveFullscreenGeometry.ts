export type SpectrumBarDirection = 'inward' | 'outward';

export function spectrumRadius(
  width: number,
  height: number,
  sizePct: number,
  maxBarDepth: number,
): number {
  const available = Math.max(24, Math.min(width, height) / 2 - maxBarDepth - 8);
  return Math.max(
    20,
    Math.min(available, available * Math.max(0.25, Math.min(2, Number(sizePct) / 100))),
  );
}

export function spectrumBarRadii(
  radius: number,
  depth: number,
  direction: SpectrumBarDirection,
  minimumInnerRadius = 8,
): { innerRadius: number; outerRadius: number } {
  const baseRadius = Math.max(8, Number(radius) || 8);
  const boundedDepth = Math.max(0, Number(depth) || 0);
  const centerBoundary = Math.max(
    8,
    Math.min(baseRadius, Number(minimumInnerRadius) || 8),
  );
  return direction === 'inward'
    ? {
        innerRadius: Math.max(centerBoundary, baseRadius - boundedDepth),
        outerRadius: baseRadius,
      }
    : {
        innerRadius: baseRadius,
        outerRadius: baseRadius + boundedDepth,
      };
}
