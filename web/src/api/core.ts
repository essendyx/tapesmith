/** Kern-Abfragen (App, Status, Bänder, Schriften, Warteschlange) und Query-Schlüssel. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut, getToken } from './client';
import type { AppInfo, FontInfo, QueueJson, StatusJson, TapeInfo } from './types';

export const qk = {
  app: ['app'],
  status: ['status'],
  tapes: ['tapes'],
  settings: ['settings'],
  history: ['history'],
  queue: ['queue'],
  recentTexts: ['recent-texts'],
  templates: ['templates'],
  gallery: ['gallery'],
  rolls: ['rolls'],
  stats: ['stats'],
  inventory: ['inventory'],
  documents: ['documents'],
  fonts: ['fonts'],
  modules: ['modules'],
} as const;

export function useAppInfo(): UseQueryResult<AppInfo> {
  return useQuery({
    queryKey: qk.app,
    queryFn: ({ signal }) => apiGet<AppInfo>('/api/v1/app', signal),
    staleTime: 60_000,
    enabled: getToken() !== null,
  });
}

export function useStatus(): UseQueryResult<StatusJson> {
  return useQuery({
    queryKey: qk.status,
    queryFn: ({ signal }) => apiGet<StatusJson>('/api/v1/status', signal),
    enabled: getToken() !== null,
  });
}

export function refreshStatus(quick?: boolean): Promise<StatusJson> {
  return apiPost<StatusJson>('/api/v1/status/refresh', quick === undefined ? {} : { quick });
}

export function fetchTapes(signal?: AbortSignal): Promise<{ tapes: TapeInfo[]; current: string }> {
  return apiGet<{ tapes: TapeInfo[]; current: string }>('/api/v1/tapes', signal);
}

export function useTapes(): UseQueryResult<{ tapes: TapeInfo[]; current: string }> {
  return useQuery({
    queryKey: qk.tapes,
    queryFn: ({ signal }) => fetchTapes(signal),
  });
}

export function setCurrentTape(id: string): Promise<{ tapes: TapeInfo[]; current: string }> {
  return apiPut<{ tapes: TapeInfo[]; current: string }>('/api/v1/tapes/current', { id });
}

export function useFonts(): UseQueryResult<{ fonts: FontInfo[] }> {
  return useQuery({
    queryKey: qk.fonts,
    queryFn: ({ signal }) => apiGet<{ fonts: FontInfo[] }>('/api/v1/labels/fonts', signal),
    staleTime: 5 * 60_000,
  });
}

/** `opts.enabled`: z. B. nur abfragen, solange die Palette offen ist. */
export function useQueueSnapshot(opts?: { enabled?: boolean }): UseQueryResult<QueueJson> {
  return useQuery({
    queryKey: qk.queue,
    queryFn: ({ signal }) => apiGet<QueueJson>('/api/v1/queue', signal),
    enabled: opts?.enabled ?? true,
  });
}
