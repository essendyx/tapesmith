/** Speichert Änderungen einer Karte über PATCH /access/settings; die Antwort ersetzt den Query-Cache. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { useNotify } from '../../components/NotifyProvider';
import { ACCESS_KEY, patchAccessSettings } from './api';
import type { AccessJson } from './types';

export interface AccessSave {
  save: (changes: Record<string, unknown>, successTitle?: string) => Promise<boolean>;
  saving: boolean;
  error: string | null;
}

export function useAccessSave(): AccessSave {
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (changes: Record<string, unknown>, successTitle?: string): Promise<boolean> => {
    if (Object.keys(changes).length === 0) return true;
    setSaving(true);
    setError(null);
    try {
      const data = await patchAccessSettings(changes);
      queryClient.setQueryData<AccessJson>(ACCESS_KEY, data);
      if (successTitle) notify({ intent: 'success', title: successTitle });
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setSaving(false);
    }
  };

  return { save, saving, error };
}
