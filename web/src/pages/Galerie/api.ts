/** Galerie-Endpunkte: Übersicht, Favoriten, Prüfung, Paket-Im-/Export. */
import { apiDelete, apiDownload, apiGet, apiPost } from '../../api/client';
import type { GalleryJson, LintIssueJson } from '../../api/types';

export function fetchGallery(query: string, category: string | null, signal?: AbortSignal): Promise<GalleryJson> {
  const params = new URLSearchParams();
  if (query) params.set('query', query);
  if (category) params.set('category', category);
  const qs = params.toString();
  return apiGet<GalleryJson>(`/api/v1/gallery${qs ? `?${qs}` : ''}`, signal);
}

export function setFavorite(name: string, favorite: boolean): Promise<{ favorites: string[] }> {
  return apiPost<{ favorites: string[] }>(`/api/v1/gallery/favorites/${encodeURIComponent(name)}`, { favorite });
}

export function fetchLint(signal?: AbortSignal): Promise<{ issues: LintIssueJson[] }> {
  return apiGet<{ issues: LintIssueJson[] }>('/api/v1/templates/lint', signal);
}

export function importPackage(packageB64: string, overwrite: boolean): Promise<{ imported: string[] }> {
  return apiPost<{ imported: string[] }>('/api/v1/templates/import', { package_b64: packageB64, overwrite });
}

export function exportPackage(names: string[]): Promise<void> {
  return apiDownload('/api/v1/templates/export', { names }, 'vorlagen.zip', 'POST');
}

export function deleteTemplate(name: string): Promise<Record<string, never>> {
  return apiDelete(`/api/v1/templates/${encodeURIComponent(name)}`);
}
