/** Endpunkte des Assistenten „Platte tauschen". */
import { apiGet, apiPost } from '../../api/client';
import type { SshHostJson } from '../../api/types';
import type { ReplacePlanJson, ZfsOverviewJson, ZfsPlanRequest } from './types';

export function fetchSshHosts(signal?: AbortSignal): Promise<{ hosts: SshHostJson[] }> {
  return apiGet<{ hosts: SshHostJson[] }>('/api/v1/ssh/hosts', signal);
}

export function scanZfs(host: string): Promise<ZfsOverviewJson> {
  return apiPost<ZfsOverviewJson>('/api/v1/homelab/zfs/scan', { host });
}

export function planZfs(req: ZfsPlanRequest): Promise<ReplacePlanJson> {
  return apiPost<ReplacePlanJson>('/api/v1/homelab/zfs/plan', req);
}
