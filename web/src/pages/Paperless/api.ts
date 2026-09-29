/** Endpunkte der Seite Paperless: ASN-Serien, Garantie-Etikett. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPost } from '../../api/client';
import type {
  AsnNextJson,
  AsnReserveJson,
  DocumentHitJson,
  DocumentSearchParams,
  WarrantyResponseJson,
} from './types';

export const paperlessKeys = {
  asnNext: ['paperless', 'asn', 'next'] as const,
  documents: (params: DocumentSearchParams) => ['paperless', 'documents', params] as const,
  warranty: (id: number, months: number | null, geraet: string) =>
    ['paperless', 'warranty', id, months, geraet] as const,
};

export function useAsnNext(): UseQueryResult<AsnNextJson> {
  return useQuery({
    queryKey: paperlessKeys.asnNext,
    queryFn: ({ signal }) => apiGet<AsnNextJson>('/api/v1/homelab/paperless/asn/next', signal),
  });
}

export function reserveAsn(count: number): Promise<AsnReserveJson> {
  return apiPost<AsnReserveJson>('/api/v1/homelab/paperless/asn/reserve', { count });
}

export function voidAsn(asn: string, reason: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/v1/homelab/paperless/asn/void', { asn, reason });
}

export function searchDocuments(
  params: DocumentSearchParams,
  signal?: AbortSignal,
): Promise<{ documents: DocumentHitJson[] }> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.correspondent) qs.set('correspondent', params.correspondent);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  const suffix = qs.toString();
  return apiGet<{ documents: DocumentHitJson[] }>(`/api/v1/homelab/paperless/documents${suffix ? `?${suffix}` : ''}`, signal);
}

export function useDocumentSearch(params: DocumentSearchParams, enabled: boolean): UseQueryResult<{ documents: DocumentHitJson[] }> {
  return useQuery({
    queryKey: paperlessKeys.documents(params),
    queryFn: ({ signal }) => searchDocuments(params, signal),
    enabled,
  });
}

export function fetchWarranty(id: number, months: number | null, geraet: string, signal?: AbortSignal): Promise<WarrantyResponseJson> {
  const qs = new URLSearchParams();
  if (months !== null) qs.set('months', String(months));
  if (geraet) qs.set('geraet', geraet);
  const suffix = qs.toString();
  return apiGet<WarrantyResponseJson>(`/api/v1/homelab/paperless/documents/${id}/warranty${suffix ? `?${suffix}` : ''}`, signal);
}

export function useWarranty(id: number | null, months: number | null, geraet: string): UseQueryResult<WarrantyResponseJson> {
  return useQuery({
    queryKey: paperlessKeys.warranty(id ?? -1, months, geraet),
    queryFn: ({ signal }) => fetchWarranty(id as number, months, geraet, signal),
    enabled: id !== null,
  });
}
