export type PinchRowBounds = { id: string; top: number; bottom: number };
export type PinchRowAnchor = { id: string; top: number; height: number; fraction: number };

/** Map native pinch scale to the existing 14–28 pt conversation-text range. */
export function pinchFontSize(startSize: number, scale: number): number {
  'worklet';
  if (!Number.isFinite(scale) || scale <= 0) return startSize;
  return Math.max(14, Math.min(28, startSize + 8 * Math.log2(scale)));
}

/** Native text layout updates only when the point size changes; the small
 *  remainder keeps finger movement continuous between real text reflows. */
export function pinchPreviewSize(size: number): {fontSize:number;lineHeight:number;scale:number} {
  'worklet';
  const fontSize = Math.round(size);
  return {fontSize,lineHeight:Math.round(fontSize*1.5),scale:size/fontSize};
}

/** Select the mounted row containing the focal point, or its nearest neighbor. */
export function choosePinchAnchor(rows: readonly PinchRowBounds[], focalY: number): PinchRowAnchor | null {
  const valid = rows.filter(row => Number.isFinite(row.top) && Number.isFinite(row.bottom) && row.bottom >= row.top);
  if (!valid.length) return null;
  let nearest = valid[0]!;
  let distance = Number.POSITIVE_INFINITY;
  for (const row of valid) {
    const gap = focalY < row.top ? row.top - focalY : focalY > row.bottom ? focalY - row.bottom : 0;
    if (gap < distance) { nearest = row; distance = gap; }
  }
  const height = nearest.bottom - nearest.top;
  return { id: nearest.id, top: nearest.top, height,
    fraction: height ? Math.max(0, Math.min(1, (focalY - nearest.top) / height)) : 0 };
}

/** Keep the touched position within a long row steady after text wraps again. */
export function restoredScrollOffset(previousOffset: number, anchor: PinchRowAnchor,
  newTop: number, newHeight: number): number {
  const before = anchor.top + anchor.fraction * anchor.height;
  const after = newTop + anchor.fraction * newHeight;
  return Math.max(0, previousOffset + after - before);
}
