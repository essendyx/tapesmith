/** Typen der Seite Obsidian-Vault. */

export interface VaultNotesJson {
  folders: string[];
  notes: string[];
}

export interface VaultTableJson {
  heading: string | null;
  headers: string[];
  rows: string[][];
}

export interface VaultNoteJson {
  path: string;
  title: string;
  values: Record<string, string>;
  tables: VaultTableJson[];
}

export interface VaultTableRequest {
  path: string;
  table: number;
  columns: Record<string, string> | null;
  template: string | null;
}

export interface VaultTableResult {
  pending_id: string;
  count: number;
  headers: string[];
}

export interface SnippetRequest {
  history_id: number | null;
  save_attachment: boolean;
  append_to: string | null;
}

export interface SnippetJson {
  history_id: number;
  file_name: string;
  png: string;
  markdown: string;
  changelog_md: string;
  summary: string;
  saved_path: string | null;
  appended: boolean;
  warnings: string[];
}

export interface PrintedRequest {
  path: string;
  history_id: number | null;
  summary?: string | null;
  force: boolean;
}

export interface PrintedJson {
  appended: boolean;
  line: string | null;
  saved_path: string | null;
  reason: string;
}

/** Ausschnitt aus GET /api/v1/homelab/settings, den die Vault-Seite braucht. */
export interface VaultSettingsJson {
  settings: {
    obsidian: {
      append_after_print: boolean;
      folders: string[];
      vault_dir: string | null;
    };
  };
}
