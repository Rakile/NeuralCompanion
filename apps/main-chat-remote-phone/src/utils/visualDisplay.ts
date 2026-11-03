export type VisualDisplay = { layout: 'fit' | 'fill'; frame: boolean };

export const DEFAULT_VISUAL_DISPLAY: VisualDisplay = { layout: 'fit', frame: true };

export function normalizeVisualDisplay(value: unknown): VisualDisplay {
  const data = value && typeof value === 'object' ? value as Partial<VisualDisplay> : {};
  return { layout: data.layout === 'fill' ? 'fill' : 'fit',
    frame: typeof data.frame === 'boolean' ? data.frame : true };
}
