/** Endpunkte für Datenträger und SSH-Disk-Scan. */
import { apiGet, apiPost } from '../../api/client';
import type { BatchPlanJson, DiskJson, DriveJson, OutcomeJson, PrintOptions, SshHostJson, SshSeriesRequest } from '../../api/types';

export function fetchDrives(signal?: AbortSignal): Promise<{ drives: DriveJson[] }> {
  return apiGet<{ drives: DriveJson[] }>('/api/v1/drives', signal);
}

export function fetchSshHosts(signal?: AbortSignal): Promise<{ hosts: SshHostJson[] }> {
  return apiGet<{ hosts: SshHostJson[] }>('/api/v1/ssh/hosts', signal);
}

export function scanSshHost(host: string): Promise<{ host: string; disks: DiskJson[] }> {
  return apiPost<{ host: string; disks: DiskJson[] }>('/api/v1/ssh/scan', { host });
}

export function planSshSeries(req: SshSeriesRequest): Promise<BatchPlanJson> {
  return apiPost<BatchPlanJson>('/api/v1/ssh/series', req);
}

export function printSshSeries(req: SshSeriesRequest, options: PrintOptions): Promise<OutcomeJson> {
  return apiPost<OutcomeJson>('/api/v1/ssh/series/print', { ...req, options });
}
