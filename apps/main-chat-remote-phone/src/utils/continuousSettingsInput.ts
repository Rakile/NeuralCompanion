import type { ContinuousSettings } from '../api/types';

export const numericSettings = ['max_turns', 'context_chars', 'recent_turns', 'max_output_tokens', 'temperature'] as const;
export type NumericSetting = typeof numericSettings[number];
export type NumericText = Partial<Record<NumericSetting, string>>;
const limits: Record<NumericSetting, [number, number, string]> = {
  max_turns: [0, 10000, 'Turn limit'], context_chars: [1000, 64000, 'Context budget'],
  recent_turns: [1, 30, 'Recent messages'], max_output_tokens: [16, 1000, 'Max Auto-Reply tokens'],
  temperature: [0, 2, 'Temperature'],
};

export function applyNumericText(settings: ContinuousSettings, edits: NumericText): ContinuousSettings {
  const result = {...settings};
  for (const key of numericSettings) {
    if (edits[key] === undefined) continue;
    const text = edits[key]!.trim().replace(',', '.');
    const [min, max, label] = limits[key];
    const value = Number(text);
    if (!/^\d+(?:\.\d*)?$/.test(text) || !Number.isFinite(value) || value < min || value > max ||
        (key !== 'temperature' && !Number.isInteger(value))) {
      throw new Error(`${label}: enter ${key === 'temperature' ? 'a number' : 'a whole number'} from ${min} to ${max}.`);
    }
    result[key] = value;
  }
  return result;
}
