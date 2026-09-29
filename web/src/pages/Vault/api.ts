/** Endpunkte der Seite Obsidian-Vault. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPost } from '../../api/client';
import type { HistoryEntryJson, TemplateSummary } from '../../api/types';
import type {
  PrintedJson,
  PrintedRequest,
  SnippetJson,
  SnippetRequest,
  VaultNoteJson,
  VaultNotesJson,
  VaultSettingsJson,
  VaultTableRequest,
  VaultTableResult,
} from './types';

export const vaultKeys = {
  notes: (folder: string) => ['vault', 'notes', folder] as const,
  note: (path: string) => ['vault', 'note', path] as const,
  settings: ['vault', 'settings'] as const,
  templates: ['vault', 'templates'] as const,
  history: ['vault', 'history'] as const,
};

export function useVaultNotes(folder: string): UseQueryResult<VaultNotesJson> {
  return useQuery({
    queryKey: vaultKeys.notes(folder),
    queryFn: ({ signal }) =>
      apiGet<VaultNotesJson>(`/api/v1/homelab/vault/notes${folder ? `?folder=${encodeURIComponent(folder)}` : ''}`, signal),
  });
}

export function useVaultNote(path: string | null): UseQueryResult<VaultNoteJson> {
  return useQuery({
    queryKey: vaultKeys.note(path ?? ''),
    queryFn: ({ signal }) => apiGet<VaultNoteJson>(`/api/v1/homelab/vault/note?path=${encodeURIComponent(path ?? '')}`, signal),
    enabled: Boolean(path),
  });
}

export function useVaultSettings(): UseQueryResult<VaultSettingsJson> {
  return useQuery({
    queryKey: vaultKeys.settings,
    queryFn: ({ signal }) => apiGet<VaultSettingsJson>('/api/v1/homelab/settings', signal),
  });
}

export function useTemplates(): UseQueryResult<{ templates: TemplateSummary[] }> {
  return useQuery({
    queryKey: vaultKeys.templates,
    queryFn: ({ signal }) => apiGet<{ templates: TemplateSummary[] }>('/api/v1/templates', signal),
  });
}

export function useRecentHistory(): UseQueryResult<{ entries: HistoryEntryJson[] }> {
  return useQuery({
    queryKey: vaultKeys.history,
    queryFn: ({ signal }) => apiGet<{ entries: HistoryEntryJson[] }>('/api/v1/history?limit=20', signal),
  });
}

export function postVaultTable(body: VaultTableRequest): Promise<VaultTableResult> {
  return apiPost<VaultTableResult>('/api/v1/homelab/vault/table', body);
}

export function postSnippet(body: SnippetRequest): Promise<SnippetJson> {
  return apiPost<SnippetJson>('/api/v1/homelab/vault/snippet', body);
}

export function postPrinted(body: PrintedRequest): Promise<PrintedJson> {
  return apiPost<PrintedJson>('/api/v1/homelab/vault/printed', body);
}

export function postAppend(path: string, line: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/v1/homelab/vault/append', { path, line });
}

export function postChangelog(title: string, entry: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/v1/homelab/vault/changelog', { title, entry });
}
