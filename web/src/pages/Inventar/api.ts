/** Endpunkte des Inventars: Boxen, Gegenstände, Suche, Verleih, Labels. */
import { apiDelete, apiGet, apiPost, apiPut } from '../../api/client';
import type {
  BoxDetailJson,
  BoxJson,
  InventoryLabelRequest,
  ItemJson,
  LoanJson,
  OutcomeJson,
  PrintOptions,
  RenderJson,
  SearchHitJson,
} from '../../api/types';

export function fetchBoxes(signal?: AbortSignal): Promise<{ boxes: BoxJson[] }> {
  return apiGet<{ boxes: BoxJson[] }>('/api/v1/inventory/boxes', signal);
}

export function fetchBoxDetail(id: string, signal?: AbortSignal): Promise<BoxDetailJson> {
  return apiGet<BoxDetailJson>(`/api/v1/inventory/boxes/${encodeURIComponent(id)}`, signal);
}

export function createBox(body: { id: string; location: string; note: string }): Promise<BoxJson> {
  return apiPost<BoxJson>('/api/v1/inventory/boxes', body);
}

export function updateBox(id: string, body: { location?: string; note?: string }): Promise<BoxJson> {
  return apiPut<BoxJson>(`/api/v1/inventory/boxes/${encodeURIComponent(id)}`, body);
}

export function deleteBox(id: string): Promise<Record<string, never>> {
  return apiDelete<Record<string, never>>(`/api/v1/inventory/boxes/${encodeURIComponent(id)}`);
}

export function createItem(body: { name: string; box_id: string | null; qty: number; note: string }): Promise<ItemJson> {
  return apiPost<ItemJson>('/api/v1/inventory/items', body);
}

export function moveItem(id: number, boxId: string | null): Promise<ItemJson> {
  return apiPut<ItemJson>(`/api/v1/inventory/items/${id}`, { box_id: boxId });
}

export function deleteItem(id: number): Promise<Record<string, never>> {
  return apiDelete<Record<string, never>>(`/api/v1/inventory/items/${id}`);
}

export function searchInventory(query: string, signal?: AbortSignal): Promise<{ hits: SearchHitJson[] }> {
  return apiGet<{ hits: SearchHitJson[] }>(`/api/v1/inventory/search?q=${encodeURIComponent(query)}`, signal);
}

export function fetchLoans(open: boolean, signal?: AbortSignal): Promise<{ loans: LoanJson[] }> {
  return apiGet<{ loans: LoanJson[] }>(`/api/v1/inventory/loans${open ? '?open=true' : ''}`, signal);
}

export function createLoan(body: { item: string; person: string; due?: string; note?: string }): Promise<LoanJson> {
  return apiPost<LoanJson>('/api/v1/inventory/loans', body);
}

export function returnLoan(id: number): Promise<LoanJson> {
  return apiPost<LoanJson>(`/api/v1/inventory/loans/${id}/return`, {});
}

export function renderInventoryLabel(req: InventoryLabelRequest, signal?: AbortSignal): Promise<RenderJson> {
  return apiPost<RenderJson>('/api/v1/inventory/labels/render', req, signal);
}

export function printInventoryLabel(req: InventoryLabelRequest, options: PrintOptions): Promise<OutcomeJson> {
  return apiPost<OutcomeJson>('/api/v1/inventory/labels/print', { ...req, options });
}
