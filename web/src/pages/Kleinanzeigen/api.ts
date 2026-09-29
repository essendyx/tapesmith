/** Endpunkte der Seite Kleinanzeigen: `/homelab/ka`. */
import { apiGet, apiPost, apiPut } from '../../api/client';
import type { ArtikelJson, ArtikelListJson, LabelResponse, NewArtikelRequest, StatusRequest, UpdateArtikelRequest } from './types';

const BASE = '/api/v1/homelab/ka';

export function fetchArtikel(params: { status?: string; query?: string } = {}, signal?: AbortSignal): Promise<ArtikelListJson> {
  const search = new URLSearchParams();
  if (params.status) search.set('status', params.status);
  if (params.query) search.set('query', params.query);
  const qs = search.toString();
  return apiGet<ArtikelListJson>(qs ? `${BASE}?${qs}` : BASE, signal);
}

export function createArtikel(body: NewArtikelRequest): Promise<ArtikelJson> {
  return apiPost<ArtikelJson>(BASE, body);
}

export function updateArtikel(id: string, body: UpdateArtikelRequest): Promise<ArtikelJson> {
  return apiPut<ArtikelJson>(`${BASE}/${encodeURIComponent(id)}`, body);
}

export function setArtikelStatus(id: string, body: StatusRequest): Promise<ArtikelJson> {
  return apiPost<ArtikelJson>(`${BASE}/${encodeURIComponent(id)}/status`, body);
}

export function fetchArtikelLabel(id: string, art: 'artikel' | 'reserviert' = 'artikel', signal?: AbortSignal): Promise<LabelResponse> {
  return apiGet<LabelResponse>(`${BASE}/${encodeURIComponent(id)}/label?art=${art}`, signal);
}
