import type { PersonaPrompts } from './types';

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length <= 100000;
const key = (value: string) => /^[a-z0-9][a-z0-9_.-]{0,127}$/.test(value);

/** Optional fields keep older desktop responses compatible. Fail closed on malformed edits. */
export function validPersonaRules(record: PersonaPrompts): boolean {
  const rules = record.technical_rules;
  if (rules !== undefined) {
    if (!object(rules) || typeof rules.legacy_enabled !== 'boolean') return false;
    for (const kind of ['avatar', 'tts'] as const) {
      if (!object(rules[kind]) || Object.keys(rules[kind]).length > 256) return false;
      if (Object.entries(rules[kind]).some(([id, row]) => !key(id) || !object(row)
        || typeof row.enabled !== 'boolean' || !text(row.text))) return false;
    }
  }
  const catalog = record.rule_catalog;
  if (catalog !== undefined) {
    if (!object(catalog) || typeof catalog.hasLegacy !== 'boolean'
      || typeof catalog.activeAvatar !== 'string' || typeof catalog.activeTts !== 'string') return false;
    for (const kind of ['avatar', 'tts'] as const) {
      const rows = catalog[kind];
      if (!Array.isArray(rows) || rows.length > 256 || rows.some(row => !object(row)
        || typeof row.id !== 'string' || !key(row.id) || typeof row.label !== 'string' || !text(row.defaultText))) return false;
      if (new Set(rows.map(row => row.id)).size !== rows.length) return false;
    }
  }
  return true;
}
