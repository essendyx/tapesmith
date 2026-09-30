/** Endpunkte der Seite Protokoll (`/api/v1/logs`). */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiDownload, apiGet } from '../../api/client';

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface LogFileJson {
  name: string;
  size: number;
  /** Änderungszeit in Unix-Sekunden. */
  mtime: number;
}

export interface LogListJson {
  files: LogFileJson[];
  daemon_log: string;
}

export interface LogLineJson {
  text: string;
  level: LogLevel | null;
}

export interface LogContentJson {
  name: string;
  size: number;
  mtime: number;
  lines: LogLineJson[];
  truncated: boolean;
}

export interface LogQuery {
  name: string;
  lines: number;
  level: LogLevel | '';
  search: string;
}

export const LOGS_KEY = ['logs'] as const;

export function useLogList(live: boolean): UseQueryResult<LogListJson> {
  return useQuery({
    queryKey: [...LOGS_KEY, 'list'],
    queryFn: ({ signal }) => apiGet<LogListJson>('/api/v1/logs', signal),
    refetchInterval: live ? 5000 : false,
  });
}

export function logContentPath(q: LogQuery): string {
  const params = new URLSearchParams({ lines: String(q.lines) });
  if (q.level) params.set('level', q.level);
  if (q.search.trim()) params.set('search', q.search.trim());
  return `/api/v1/logs/${encodeURIComponent(q.name)}?${params.toString()}`;
}

export function useLogContent(q: LogQuery | null, live: boolean): UseQueryResult<LogContentJson> {
  return useQuery({
    queryKey: [...LOGS_KEY, 'content', q],
    queryFn: ({ signal }) => apiGet<LogContentJson>(logContentPath(q as LogQuery), signal),
    enabled: q !== null,
    refetchInterval: live ? 2000 : false,
    placeholderData: (previous) => previous,
  });
}

export function downloadLog(name: string): Promise<void> {
  return apiDownload(`/api/v1/logs/${encodeURIComponent(name)}/download`, undefined, `${name}.txt`);
}
