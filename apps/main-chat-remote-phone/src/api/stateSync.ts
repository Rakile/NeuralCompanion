import { Buffer } from 'buffer';
import type { RemoteState } from './types';

type Cursor = { context: string; epoch: string; revision: number };
type RecordValue = Record<string, unknown>;
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const forbidden = new Set(['__proto__', 'prototype', 'constructor']);
const record = (v: unknown): v is RecordValue => v !== null && typeof v === 'object' && !Array.isArray(v);
const owns = (value: object, key: string): boolean => Object.prototype.hasOwnProperty.call(value, key);
function clone<T>(v: T): T { return JSON.parse(JSON.stringify(v)); }
export class StateSyncResyncRequired extends Error {
  constructor() { super('State synchronization needs a fresh snapshot.'); }
}
export class StateSyncVersionError extends Error {
  constructor() { super('Update NC Desktop and NC Remote together (state protocol 1 required).'); }
}
function validate(value: unknown, depth = 0): void {
  if (depth > 64) throw new StateSyncResyncRequired();
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
  if (typeof value === 'number' && Number.isFinite(value)) return;
  if (Array.isArray(value)) { for (const item of value) validate(item, depth + 1); return; }
  if (!record(value)) throw new StateSyncResyncRequired();
  for (const [key, item] of Object.entries(value)) {
    if (forbidden.has(key)) throw new StateSyncResyncRequired();
    validate(item, depth + 1);
  }
}
function pathValue(value: unknown): string[] {
  if (!Array.isArray(value) || !value.length || value.length > 32
    || !value.every(k => typeof k === 'string' && k.length <= 512 && !forbidden.has(k)))
    throw new StateSyncResyncRequired();
  return value;
}

/** Only synchronization responses update this baseline, never fast UI events. */
export class StateSyncDecoder {
  private baseline: RemoteState | null = null;
  private current: Cursor | null = null;
  reset(): void { this.baseline = null; this.current = null; }
  cursor(): Cursor | null { return this.current ? { ...this.current } : null; }
  apply(value: unknown): { state: RemoteState; full: boolean } {
    if (!record(value) || value.version !== 1) throw new StateSyncVersionError();
    const e = value;
    if (typeof e.context !== 'string' || !uuid.test(e.context) || typeof e.epoch !== 'string' || !uuid.test(e.epoch)
      || !Number.isSafeInteger(e.revision) || Number(e.revision) < 1) throw new StateSyncResyncRequired();
    const next = {context:e.context, epoch:e.epoch, revision:e.revision as number};
    validate(e);
    if (Buffer.byteLength(JSON.stringify(e), 'utf8') > (e.kind === 'full' ? 64 : 16) * 1024 * 1024)
      throw new StateSyncResyncRequired();
    let result: RemoteState;
    if (e.kind === 'full') {
      if (!record(e.state) || (this.current?.epoch === next.epoch && this.current?.context === next.context
        && next.revision <= this.current.revision)) throw new StateSyncResyncRequired();
      result = clone(e.state) as RemoteState;
    } else {
      if (!this.baseline || !this.current || next.epoch !== this.current.epoch || next.context !== this.current.context)
        throw new StateSyncResyncRequired();
      if (e.kind === 'unchanged') {
        if (next.revision !== this.current.revision) throw new StateSyncResyncRequired();
        return {state:clone(this.baseline), full:false};
      }
      if (e.kind !== 'patch' || e.base_revision !== this.current.revision || next.revision !== this.current.revision + 1
        || !Array.isArray(e.set) || !Array.isArray(e.remove) || e.set.length + e.remove.length > 4096)
        throw new StateSyncResyncRequired();
      const operations = [...e.set.map(op => {
        if (!record(op) || !owns(op, 'value')) throw new StateSyncResyncRequired();
        return {path:pathValue(op.path), value:op.value, remove:false};
      }), ...e.remove.map(path => ({path:pathValue(path), value:undefined, remove:true}))];
      const paths = new Set(operations.map(op => JSON.stringify(op.path)));
      if (paths.size !== operations.length) throw new StateSyncResyncRequired();
      for (const {path} of operations) for (let n = 1; n < path.length; ++n)
        if (paths.has(JSON.stringify(path.slice(0, n)))) throw new StateSyncResyncRequired();
      result = clone(this.baseline);
      for (const op of operations) {
        let parent: RecordValue = result as RecordValue;
        for (const key of op.path.slice(0, -1)) {
          if (!owns(parent, key) || !record(parent[key])) throw new StateSyncResyncRequired();
          parent = parent[key] as RecordValue;
        }
        const key = op.path[op.path.length - 1]!;
        if (op.remove) {
          if (!owns(parent, key)) throw new StateSyncResyncRequired();
          delete parent[key];
        } else parent[key] = clone(op.value);
      }
    }
    this.baseline = clone(result); this.current = next;
    return {state:result, full:e.kind === 'full'};
  }
}
