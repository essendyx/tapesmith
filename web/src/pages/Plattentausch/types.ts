/** Typen des Assistenten „Platte tauschen". `DiskJson`/`SshHostJson` kommen aus `api/types`. */
import type { DiskJson } from '../../api/types';

export interface PoolDeviceJson {
  pool: string;
  vdev: string | null;
  name: string;
  state: string;
  read: string;
  write: string;
  cksum: string;
  note: string;
  was_path: string | null;
  by_id: string | null;
  partition: string | null;
  device: string | null;
}

export interface PoolStatusJson {
  name: string;
  state: string;
  errors: string;
  devices: PoolDeviceJson[];
}

export interface CandidateJson {
  disk: DiskJson;
  reason: string;
}

export interface ZfsOverviewJson {
  host: string;
  scanned_at: string;
  previous_scanned_at: string | null;
  disks: DiskJson[];
  pools: PoolStatusJson[];
  problems: PoolDeviceJson[];
  candidates: CandidateJson[];
}

export interface LabelValuesJson {
  template: string;
  values: Record<string, string>;
}

export interface ReplacePlanJson {
  host: string;
  pool: string;
  old: PoolDeviceJson;
  old_serial: string;
  old_model: string;
  new: DiskJson;
  command: string;
  hints: string[];
  changelog_md: string;
  old_label: LabelValuesJson;
  new_label: LabelValuesJson;
}

export interface ZfsPlanRequest {
  host: string;
  old: string;
  new_device: string;
  slot: string;
  reason?: string;
}
