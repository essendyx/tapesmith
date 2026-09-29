/** Ungespeicherte Änderungen einer Karte: überschreibt einzelne Schlüssel, bis gespeichert/verworfen wird. */
import { useState } from 'react';

export interface SectionEdit<T extends object> {
  values: T;
  isChanged: (key: keyof T) => boolean;
  dirty: boolean;
  set: <K extends keyof T>(key: K, value: T[K]) => void;
  discard: () => void;
  /** Nur die geänderten Schlüssel, mit dem Sektions-Präfix (z. B. `"lan.enabled"`). */
  changes: (prefix: string) => Record<string, unknown>;
}

export function useSectionEdit<T extends object>(server: T): SectionEdit<T> {
  const [pending, setPending] = useState<Partial<T>>({});
  const values = { ...server, ...pending };
  const isChanged = (key: keyof T): boolean => Object.prototype.hasOwnProperty.call(pending, key);
  const dirty = Object.keys(pending).length > 0;
  const set = <K extends keyof T>(key: K, value: T[K]): void => setPending((p) => ({ ...p, [key]: value }));
  const discard = (): void => setPending({});
  const changes = (prefix: string): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(pending)) out[`${prefix}.${key}`] = (pending as Record<string, unknown>)[key];
    return out;
  };
  return { values, isChanged, dirty, set, discard, changes };
}
