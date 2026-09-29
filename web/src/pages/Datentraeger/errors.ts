/** Fehlermeldung aus einem fehlgeschlagenen API-Aufruf (ApiError.message/.hint), sonst Text der Ausnahme. */
import { ApiError } from '../../api/client';

export function errorText(err: unknown): { title: string; hint?: string } {
  if (err instanceof ApiError) return { title: err.message, hint: err.hint || undefined };
  return { title: err instanceof Error ? err.message : String(err) };
}
