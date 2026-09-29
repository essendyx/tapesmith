/** Verwaltet ungespeicherte Änderungen aller generischen Einstellungsfelder (kartenübergreifend geteilt). */
import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { qk } from '../../api/core';
import { patchSettings } from './api';

export interface SettingsEditor {
  pending: Record<string, unknown>;
  isChanged(key: string): boolean;
  setValue(key: string, value: unknown): void;
  discard(keys: string[]): void;
  save(sectionId: string, keys: string[]): Promise<boolean>;
  savingSection: string | null;
  errorFor(sectionId: string): string | null;
  restartHint(keys: string[], allRestartKeys: string[]): boolean;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function useSettingsEditor(): SettingsEditor {
  const client = useQueryClient();
  const [pending, setPending] = useState<Record<string, unknown>>({});
  const [savingSection, setSavingSection] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  const isChanged = useCallback((key: string) => Object.prototype.hasOwnProperty.call(pendingRef.current, key), []);

  const setValue = useCallback((key: string, value: unknown) => {
    setPending((prev) => ({ ...prev, [key]: value }));
  }, []);

  const discard = useCallback((keys: string[]) => {
    setPending((prev) => {
      const next = { ...prev };
      for (const k of keys) delete next[k];
      return next;
    });
  }, []);

  const save = useCallback(
    async (sectionId: string, keys: string[]): Promise<boolean> => {
      const changes: Record<string, unknown> = {};
      for (const k of keys) {
        if (Object.prototype.hasOwnProperty.call(pendingRef.current, k)) changes[k] = pendingRef.current[k];
      }
      if (Object.keys(changes).length === 0) return true;
      setSavingSection(sectionId);
      setErrors((prev) => ({ ...prev, [sectionId]: null }));
      try {
        const fresh = await patchSettings(changes);
        client.setQueryData(qk.settings, fresh);
        setPending((prev) => {
          const next = { ...prev };
          for (const k of Object.keys(changes)) delete next[k];
          return next;
        });
        // Sprache und Farbschema (`app.*`) wirken sofort: AppInfo neu laden, damit i18n und Theme folgen.
        if (Object.keys(changes).some((k) => k.startsWith('app.'))) {
          await client.invalidateQueries({ queryKey: qk.app });
        }
        return true;
      } catch (err) {
        setErrors((prev) => ({ ...prev, [sectionId]: errorMessage(err) }));
        return false;
      } finally {
        setSavingSection(null);
      }
    },
    [client],
  );

  const errorFor = useCallback((sectionId: string) => errors[sectionId] ?? null, [errors]);

  const restartHint = useCallback(
    (keys: string[], allRestartKeys: string[]) => keys.some((k) => allRestartKeys.includes(k)),
    [],
  );

  return { pending, isChanged, setValue, discard, save, savingSection, errorFor, restartHint };
}
