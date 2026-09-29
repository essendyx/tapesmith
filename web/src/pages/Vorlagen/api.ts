/** Vorlagen-Endpunkte: Liste, Details, Löschen, Datei prüfen, Belegung exportieren. */
import { apiDelete, apiDownload, apiGet, apiPost } from '../../api/client';
import type { TemplateDetail, TemplateSummary } from '../../api/types';

export function fetchTemplates(signal?: AbortSignal): Promise<{ templates: TemplateSummary[] }> {
  return apiGet<{ templates: TemplateSummary[] }>('/api/v1/templates', signal);
}

export function fetchTemplateDetail(name: string, signal?: AbortSignal): Promise<TemplateDetail> {
  return apiGet<TemplateDetail>(`/api/v1/templates/${encodeURIComponent(name)}`, signal);
}

export function deleteTemplate(name: string): Promise<Record<string, never>> {
  return apiDelete(`/api/v1/templates/${encodeURIComponent(name)}`);
}

export function parseTemplateFile(name: string, dataB64: string): Promise<{ definition: Record<string, unknown>; name: string }> {
  return apiPost('/api/v1/templates/parse-file', { name, data_b64: dataB64 });
}

export function exportAssignment(name: string, values: Record<string, string>): Promise<void> {
  return apiDownload(`/api/v1/templates/${encodeURIComponent(name)}/assignment`, { values }, `${name}-belegung.csv`, 'POST');
}
