/** Geheimwerte aller Dienste (`/api/v1/secrets`): nur Zustand, nie der Wert. */
import { useQuery, type QueryClient, type UseQueryResult } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPost, apiPut } from './client';

/** `tapesmith`: in den Windows-Anmeldeinformationen unter Tapesmith; `extern`: Datei, Umgebungsvariable o. Ä. */
export type SecretSource = 'tapesmith' | 'extern' | 'none';

export interface SecretSlot {
  id: string;
  label: string;
  source: SecretSource;
  set: boolean;
  /** Modul, zu dem der Slot gehört; `null`: Kernfunktion (Seite Zugriff). */
  module?: string | null;
  /** Ist das Modul eingeschaltet? Ohne Modul immer `true`. */
  module_enabled?: boolean;
  /** Ort in der Oberfläche, an dem der Dienst eingerichtet wird. */
  target?: string;
}

export interface AdoptAllResult {
  adopted: string[];
  skipped: { id: string; label: string; reason: string }[];
  slots: SecretSlot[];
}

export const SECRETS_KEY = ['secrets'] as const;

export function useSecrets(): UseQueryResult<{ slots: SecretSlot[] }> {
  return useQuery({
    queryKey: SECRETS_KEY,
    queryFn: ({ signal }) => apiGet<{ slots: SecretSlot[] }>('/api/v1/secrets', signal),
  });
}

function slotPath(id: string): string {
  return `/api/v1/secrets/${encodeURIComponent(id)}`;
}

export function putSecret(id: string, value: string): Promise<SecretSlot> {
  return apiPut<SecretSlot>(slotPath(id), { value });
}

export function adoptSecret(id: string): Promise<SecretSlot> {
  return apiPost<SecretSlot>(`${slotPath(id)}/adopt`, {});
}

/** Übernimmt alle Slots mit externer Quelle; leere Quellen werden mit Grund übersprungen. */
export function adoptAllSecrets(): Promise<AdoptAllResult> {
  return apiPost<AdoptAllResult>('/api/v1/secrets/adopt-all', {});
}

export function deleteSecret(id: string): Promise<SecretSlot> {
  return apiDelete<SecretSlot>(slotPath(id));
}

/** Nach einer Änderung: Zustand der Geheimwerte und die Seiten, die ihn anzeigen, neu laden. */
export function refreshSecretViews(client: QueryClient): void {
  for (const queryKey of [SECRETS_KEY, ['access'], ['homelab']]) void client.invalidateQueries({ queryKey });
}
