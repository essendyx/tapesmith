/** Auto-Update: Zustand, Prüfen, Installieren, Rückstellung. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPost, getToken } from './client';

export type UpdateState = 'idle' | 'checking' | 'downloading' | 'ready' | 'installing' | 'failed';

export interface UpdateAvailable {
  version: string;
  notes: string;
  published: string;
  size: number;
}

export interface UpdateStatus {
  installed: boolean;
  installed_elsewhere?: boolean;
  current: string;
  previous: string | null;
  root: string | null;
  enabled: boolean;
  source: string;
  channel: 'stable' | 'beta';
  auto_install: boolean;
  last_check: string | null;
  available: UpdateAvailable | null;
  state: UpdateState;
  error: { code: string; message: string } | null;
  can_rollback: boolean;
  idle_ok: boolean;
  /** Einmalige Rückfrage nach der automatischen Prüfung offen (installierte App, noch nie gefragt). */
  consent_needed: boolean;
}

export const UPDATE_QUERY_KEY = ['update'] as const;

/** Zustände, in denen die Oberfläche alle 2 s nachfragt. */
export const UPDATE_BUSY_STATES: readonly UpdateState[] = ['checking', 'downloading', 'installing'];

/** Abstand der Nachfrage in laufenden Zuständen (ms). */
export const UPDATE_POLL_MS = 2000;

/**
 * Zustand der Updates. Fragt alle 2 s nach, solange der Dienst beschäftigt ist oder `poll` gesetzt
 * ist (z. B. direkt nach dem Start einer Installation, die der Dienst erst im Hintergrund vorbereitet).
 */
export function useUpdateStatus(opts?: { poll?: boolean }): UseQueryResult<UpdateStatus> {
  const poll = opts?.poll ?? false;
  return useQuery({
    queryKey: UPDATE_QUERY_KEY,
    queryFn: ({ signal }) => apiGet<UpdateStatus>('/api/v1/update/status', signal),
    enabled: getToken() !== null,
    refetchInterval: (query) => {
      const state = (query.state.data as UpdateStatus | undefined)?.state;
      return poll || (state && UPDATE_BUSY_STATES.includes(state)) ? UPDATE_POLL_MS : false;
    },
  });
}

/** Antwort auf die Rückfrage: automatische Prüfung ein oder aus (danach fragt die Oberfläche nicht mehr). */
export function answerUpdateConsent(enabled: boolean): Promise<UpdateStatus> {
  return apiPost<UpdateStatus>('/api/v1/update/consent', { enabled });
}

export function checkUpdate(): Promise<UpdateStatus> {
  return apiPost<UpdateStatus>('/api/v1/update/check');
}

export function installUpdate(
  version: string,
  reopenRoute: string | null,
  explicit = false,
): Promise<{ started: boolean }> {
  return apiPost<{ started: boolean }>('/api/v1/update/install', { version, reopen_route: reopenRoute, explicit });
}

/** Ein Eintrag der Versionsauswahl (Quelle und lokal vorhandene Versionen). */
export interface UpdateVersion {
  version: string;
  published: string | null;
  notes: string;
  prerelease: boolean;
  current: boolean;
  installed: boolean;
  failed: boolean;
  newer: boolean;
  in_source: boolean;
}

export interface UpdateVersions {
  versions: UpdateVersion[];
  error: { code: string; message: string; hint?: string } | null;
  current: string;
  installed: boolean;
  channel: 'stable' | 'beta';
}

export const UPDATE_VERSIONS_KEY = ['update', 'versions'] as const;

/** Alle installierbaren Versionen, neueste zuerst; der Dienst speichert die Liste 10 Minuten zwischen. */
export function useUpdateVersions(prerelease: boolean, enabled: boolean): UseQueryResult<UpdateVersions> {
  return useQuery({
    queryKey: [...UPDATE_VERSIONS_KEY, prerelease],
    queryFn: ({ signal }) =>
      apiGet<UpdateVersions>(`/api/v1/update/versions${prerelease ? '?prerelease=true' : ''}`, signal),
    enabled: enabled && getToken() !== null,
    staleTime: 60_000,
  });
}

export function rollbackUpdate(reopenRoute: string | null = null): Promise<{ started: boolean }> {
  return apiPost<{ started: boolean }>('/api/v1/update/rollback', { reopen_route: reopenRoute });
}
