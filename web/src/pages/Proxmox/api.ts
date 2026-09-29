/** Endpunkte der Seite Proxmox. */
import { apiGet, apiPost } from '../../api/client';
import type { GuestsJson, GuestsRequest, PveHostsJson, TableJson, TableRequest } from './types';

export function fetchPveHosts(signal?: AbortSignal): Promise<PveHostsJson> {
  return apiGet<PveHostsJson>('/api/v1/homelab/proxmox/hosts', signal);
}

export function fetchGuests(req: GuestsRequest): Promise<GuestsJson> {
  return apiPost<GuestsJson>('/api/v1/homelab/proxmox/guests', req);
}

export function prepareTable(req: TableRequest): Promise<TableJson> {
  return apiPost<TableJson>('/api/v1/homelab/proxmox/table', req);
}
