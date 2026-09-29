/** Typen der Seite Proxmox (Endpunkte /api/v1/homelab/proxmox/*). */

export interface PveHostJson {
  name: string;
  url: string;
  verify_tls: boolean;
  token_set: boolean;
  token_describe: string;
}

export interface PveHostsJson {
  hosts: PveHostJson[];
}

export type GuestKind = 'qemu' | 'lxc';

export interface NodeJson {
  host: string;
  node: string;
  status: string;
  ip: string | null;
}

export interface GuestJson {
  host: string;
  node: string;
  vmid: number;
  kind: GuestKind;
  name: string;
  status: string;
  tags: string[];
  ips: string[];
  /** "" oder "IP unbekannt: …" */
  ip_note: string;
  passthrough: string[];
  ip_kurz: string;
}

export interface GuestsRequest {
  host: string;
  status?: string;
  kind?: GuestKind;
  ids?: string;
  name?: string;
}

export interface GuestsJson {
  host: string;
  nodes: NodeJson[];
  guests: GuestJson[];
  warnings: string[];
}

export interface TableRequest {
  host: string;
  vmids: number[];
  links: boolean;
}

export interface TableJson {
  pending_id: string;
  template: 'vm-lxc-qr' | 'vm-lxc';
  count: number;
  warnings: string[];
}
