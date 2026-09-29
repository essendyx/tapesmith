/* Typen der HTTP-API v1. Verbindlich für Backend und Frontend. */

// ---------- allgemein ----------
export type Role = 'success' | 'secondary' | 'warning' | 'error';
/** `code`: stabiler Fehlercode; ältere Antworten ohne `code` gelten als `http.error`. */
export interface ApiErrorJson { kind: string; code?: string; message: string; hint: string; exit_code: number; details: Record<string, unknown> | null }
export interface ApiErrorBody { error: ApiErrorJson }

// ---------- App, Profil, Band ----------
export interface ProfileInfo {
  model: string; head_dots: number; content_dots: number; content_offset: number; dots_per_mm: number;
  leader_mm: number; trailer_mm: number; length_factor: number; verified: string[]; experimental: string[];
}
/** Farben als "#rrggbb". */
export interface TapeInfo {
  id: string; name: string; background: string; ink: string; material: string; transparent: boolean;
  dark: boolean; code_mode: string; density: number | null; current: boolean;
}
export interface AppInfo {
  version: string; home_key: string; pid: number; port: number; accent: string | null;
  profile: ProfileInfo; tape: TapeInfo; screen_px_per_mm: number | null; ctrl_enter_only: boolean;
  /** Einstellung `app.language`. */
  language: 'auto' | 'de' | 'en';
  /**
   * Vom Dienst aufgelöste Sprache (`TAPESMITH_LANG`, `app.language`, sonst Windows-Anzeigesprache);
   * bei "auto" folgt ihr die Oberfläche. Ältere Dienste melden sie nicht.
   */
  resolved_language?: 'de' | 'en';
  /** Windows-Anzeigesprache des Dienstes (jede andere Sprache als de/en ergibt en). */
  system_language?: 'de' | 'en';
  /** Einstellung `app.theme`. */
  theme: 'system' | 'hell' | 'dunkel';
  /** Eingeschaltete Module (`modules.enabled`, siehe `src/modules`). */
  modules: string[];
}

// ---------- Status ----------
export interface StateInfo { state: string; transport: string | null; last_error: string | null; leased: boolean }
export interface StatusValueJson { value: unknown; text: string; verified: boolean; raw: string }
export interface PrinterStatusJson { answered: boolean; values: Record<string, StatusValueJson>; unknown: string[]; raw: string }
export interface StatusReportJson { state: StateInfo; status: PrinterStatusJson | null; checked_at: string | null }
export interface StatusView { chip: string; role: Role; title: string; detail: string; tooltip: string }
export interface StatusJson { report: StatusReportJson; view: StatusView }

// ---------- Druck ----------
export interface PrintOptions {
  copies: number; chain: boolean; cut_marks: boolean; confirmed: boolean;
  cut_pause_s: number | null; job_key: string | null; enqueue_on_offline: boolean;
}
export const DEFAULT_PRINT_OPTIONS: PrintOptions = {
  copies: 1, chain: false, cut_marks: true, confirmed: false, cut_pause_s: null, job_key: null, enqueue_on_offline: true,
};
export type OutcomeStatus = 'ok' | 'abgebrochen' | 'unvollständig' | 'abgelehnt' | 'bestätigung_nötig' | 'wartet'; // i18n-ignore (Server-Werte)
export interface OutcomeJson {
  status: OutcomeStatus; warnings: string[]; reasons: string[]; history_id: number | null; consumed_mm: number;
  results: { rows: number; rows_sent: number | null; waited_s: number; status: string }[];
  printer_status: PrinterStatusJson | null;
  error: { kind: string; message: string; exit_code: number; rows_sent: number | null; rows_total: number | null } | null;
  queue_id: number | null; job_key: string; title: string; balance_text: string;
}

// ---------- Label-Quellen ----------
export interface TextSource {
  kind: 'text'; lines: string[]; font?: string; align?: 'left' | 'center' | 'right'; font_size?: number | null;
  /** Feste Texthöhe in mm (passt sie nicht, wird verkleinert und gewarnt). */
  text_height_mm?: number | null;
  max_length_mm?: number | null; fixed_length_mm?: number | null; margin_mm?: number; qr?: string | null;
  qr_error?: 'l' | 'm' | 'q' | 'h';
}
/** `definition`: komplette Vorlage (JSON wie *.tapesmith.json), z. B. aus einer Datei; dann ist `template` nur der Anzeigename. */
export interface TemplateSource { kind: 'template'; template: string; values: Record<string, string>; definition?: Record<string, unknown> }
export interface DocumentSource { kind: 'document'; document: LabelDocumentJson; title?: string }
export type QrContentInput =
  | { type: 'url'; url: string; uppercase?: boolean }
  | { type: 'text'; text: string }
  | { type: 'wifi'; ssid: string; password: string; security: 'WPA' | 'WEP' | 'nopass'; hidden: boolean }
  | { type: 'vcard'; name: string; phone?: string; email?: string; org?: string; url?: string };
export interface QrSource { kind: 'qr'; content: QrContentInput; lines: string[]; error: 'auto' | 'l' | 'm' | 'q' | 'h'; max_length_mm?: number | null }
/** Nachdruck aus dem Verlauf; `values` ergänzt fehlende sensible Felder. */
export interface HistorySource { kind: 'history'; id: number; values?: Record<string, string> }
export interface CalibrationSource { kind: 'calibration'; which: 'ruler' | 'edge' }
export interface TestSource { kind: 'test' }
export type LabelSource = TextSource | TemplateSource | DocumentSource | QrSource | HistorySource | CalibrationSource | TestSource;

export interface PreviewJson {
  design_png: string; raster_png: string; width: number; height: number; info: string;
  content_mm: number; tape_mm: number; labels: number; jobs: number; estimated: boolean; balance_text: string;
  decision: { allowed: boolean; needs_confirmation: boolean; reasons: string[] }; warnings: string[];
}
export interface ObjectIssueJson { object_id: string | null; level: 'error' | 'warning'; message: string }
/** `checked=false`: der Code wurde mangels Decoder auf diesem PC gar nicht erst rückgelesen (kein Fehler, `decodes` dann immer `false`). */
export interface CodeInfoJson { kind: 'qr' | 'code128' | 'datamatrix'; module_dots: number; decodes: boolean; checked: boolean; inverted: boolean; version: number | null }
/** Nur bei Dokument-Quellen: Inhalt im Dokument-Koordinatensystem (1 px = 1 Druckpunkt, ohne Label-Spiegelung/-Drehung). */
export interface EditorOverlay {
  png: string; width: number; height: number; boxes: Record<string, [number, number, number, number]>;
  font_sizes: Record<string, number>; codes: Record<string, CodeInfoJson>;
}
export interface FixJson { id: string; label: string; source: LabelSource }
/** `checked=false`: der Code wurde mangels Decoder auf diesem PC gar nicht erst rückgelesen (kein Fehler, `decodes` dann immer `false`). */
export interface QrInfo { version: number; error: string; module_dots: number; decodes: boolean; checked: boolean; warnings: string[]; text: string }
export interface RenderJson {
  ok: boolean; title: string; preview: PreviewJson | null; errors: string[]; warnings: string[];
  issues: ObjectIssueJson[]; fixes: FixJson[]; font_size: number | null; qr: QrInfo | null;
  values: Record<string, string> | null; shortened: string[]; notes: string[]; tape_reason: string | null;
  missing_secrets: string[]; editor: EditorOverlay | null;
}
export interface FontInfo { id: string; name: string }

// ---------- Dokument (Editor, Format wie document_to_dict) ----------
export type ObjectKind = 'text' | 'qr' | 'code128' | 'datamatrix' | 'icon' | 'line' | 'rect' | 'image';
export interface LabelObjectJson {
  kind: ObjectKind; id: string; x: number; y: number; w: number; h: number;
  rotation?: 0 | 90 | 180 | 270; mirror?: boolean; locked?: boolean; visible?: boolean; name?: string;
  [prop: string]: unknown;
}
export interface LabelDocumentJson {
  version: number; objects: LabelObjectJson[]; length_mode?: 'auto' | 'fixed' | 'max'; length_mm?: number | null;
  margin_mm?: number; mirror?: boolean; rotate180?: boolean;
}
export type EditorPreset = 'text' | 'qr' | 'code128' | 'datamatrix' | 'icon' | 'line' | 'arrow' | 'rect' | 'warnbar' | 'image';
export type EditOp =
  | 'move' | 'set_box' | 'update' | 'remove' | 'duplicate' | 'align' | 'distribute' | 'reorder'
  | 'rotate' | 'flip' | 'label_transform' | 'set_length';
/** params je op: move {dx,dy,snap?:boolean} · set_box {x,y,w,h} · update {changes:{...}} · remove {} · duplicate {}
 *  align {mode:'left'|'hcenter'|'right'|'top'|'vcenter'|'bottom', reference:'selection'|'label'} · distribute {axis:'h'|'v'} (mind. 3 Objekte)
 *  reorder {op:'raise'|'lower'|'top'|'bottom'} · rotate {degrees:90|-90|180|-180} · flip {} · label_transform {mirror?:boolean, rotate180?:boolean}
 *  set_length {mode:'auto'|'fixed'|'max', length_mm?:number|null} */
export interface EditOpRequest { document: LabelDocumentJson; op: EditOp; ids: string[]; params: Record<string, unknown> }
/** Hilfslinie: axis 'x' = senkrechte Linie bei x = pos (Python orientation 'v'), 'y' = waagerechte bei y = pos ('h'); label = Python kind ('center'|'edge'|'object'|'grid'). */
export interface Guide { axis: 'x' | 'y'; pos: number; label: string }
export interface EditResult { document: LabelDocumentJson; selected: string[]; step_label: string; guides: Guide[] }
/** handle bei resize: 'n'|'s'|'e'|'w'|'ne'|'nw'|'se'|'sw'. */
export interface SnapRequest { document: LabelDocumentJson; ids: string[]; dx: number; dy: number; mode: 'move' | 'resize'; handle?: string; grid?: number }
export interface SnapResult { dx: number; dy: number; guides: Guide[] }
export interface DocumentInfo { name: string; modified: string; objects: number }
/** `category` ist eine Kennung (für die Suche), `category_label` ihr Anzeigename in der Sprache der Anfrage. */
export interface IconInfoJson { ref: string; name: string; category: string; category_label?: string; source: 'tabler' | 'simple' | 'user' }
export interface TargetJson { id: string; name: string; max_length_mm: number | null; note: string }

// ---------- Vorlagen, Galerie, Serien ----------
export type FieldType = 'fixed' | 'input' | 'date' | 'counter' | 'lookup';
export interface FieldJson {
  id: string; label: string; type: FieldType; default: string; required: boolean; secret: boolean;
  choices: string[]; max_len: number | null; multiline: boolean;
  /** Anzeige je Auswahlwert (der Wert selbst wird gedruckt); fehlt ein Wert, gilt er selbst. */
  choice_labels?: Record<string, string>;
  /** "text_size": Feld schriftgroesse (auto, auto-feld oder Texthöhe in mm). */
  role?: 'text_size' | null;
  /** Standardwert eines leeren Felds (z. B. Generator-Parameter raster_mm) für den Platzhalter. */
  default_hint?: string | null;
}
export interface TemplateSummary {
  /** Stabile ID (Dateiname, Verlauf, CLI); `title` ist der Anzeigename in der Sprache der Anfrage. */
  name: string; title?: string; description: string; category: string; tags: string[]; kind: 'layout' | 'document' | 'generator';
  builtin: boolean; favorite: boolean; target: string | null; tapes: string[]; default_copies: number;
  input_fields: FieldJson[]; sample: Record<string, string>;
}
export interface TemplateDetail extends TemplateSummary { fields: FieldJson[]; path: string | null; definition: Record<string, unknown>; tape_reason: string | null }
export interface SaveTemplateRequest {
  name: string; description: string; category: string; tags: string[];
  document?: LabelDocumentJson; definition?: Record<string, unknown>; overwrite: boolean;
}
export interface LintIssueJson { template: string; level: 'error' | 'warning'; message: string }
export interface GalleryJson {
  categories: { name: string; templates: TemplateSummary[] }[]; favorites: string[]; recent: string[]; templates_dir: string;
}
export type BatchSourceInput =
  | { type: 'text'; text: string; has_header?: boolean | null }                 // CSV/TSV/Zwischenablage
  | { type: 'file'; name: string; data_b64: string; sheet?: string | null; has_header?: boolean | null }   // .csv/.xlsx
  | { type: 'lines'; text: string }                                             // eine Zeile pro Label
  | { type: 'series'; fields: Record<string, string>; count: number | null }    // z. B. {"port": "1..24"}
  | { type: 'pending'; id: string };                                            // aus /integration/pending
export interface BatchTableRequest { source: BatchSourceInput }
export interface BatchTableJson { headers: string[]; rows: string[][]; source_name: string }
export interface BatchRequest {
  template: string; source: BatchSourceInput; mapping: Record<string, string> | null;   // Feld-ID -> Spaltenname
  selected: number[] | null; fixed: Record<string, string>; chain: boolean; cut_marks: boolean;
}
export interface BatchPlanJson {
  count: number; summary: string; mapping: Record<string, string>; headers: string[];
  warnings: string[]; errors: string[]; previews: { index: number; title: string; design_png: string }[];
}

// ---------- Verlauf, Warteschlange, Statistik ----------
export interface HistoryEntryJson {
  id: number; created: string; source: string; kind: string; title: string; template: string | null;
  values: Record<string, string>; spec: Record<string, unknown> | null; length_mm: number; tape_mm: number;
  copies: number; chained: boolean; status: string; error: string; sensitive: boolean; has_head: boolean;
  reprintable: boolean; missing_secrets: string[];
}
export interface QueuedJobJson {
  id: number; created: string; source: string; title: string; state: string; position: number; attempts: number;
  next_try: string | null; last_error: string; sensitive: boolean; history_id: number | null;
}
export interface QueueJson { jobs: QueuedJobJson[]; paused: boolean; auto_retry: boolean; next_try: string | null; probe: string; waiting_reason: string }
export interface UsageRowJson { key: string; jobs: number; labels: number; tape_mm: number }
export interface StatsJson { by: string; rows: UsageRowJson[]; totals: UsageRowJson }
export interface RollUsageJson { tape_id: string; tape_name: string; started: string; length_mm: number; used_mm: number; jobs: number; finished: boolean; factor: number }

// ---------- Inventar ----------
export interface BoxJson { id: string; location: string; note: string; created: string; items: number }
export interface ItemJson { id: number; box_id: string | null; name: string; qty: number; note: string }
export interface BoxDetailJson extends BoxJson { item_list: ItemJson[] }
export interface LoanJson { id: number; item: string; person: string; since: string; due: string | null; returned: string | null; note: string; open: boolean; overdue: boolean }
export interface SearchHitJson { item: ItemJson; box: BoxJson | null; text: string }
export type InventoryLabelRequest = { type: 'box'; box_id: string } | { type: 'content'; box_id: string } | { type: 'loan'; loan_id: number };

// ---------- Datenträger, SSH ----------
export interface DriveJson { root: string; label: string; size_bytes: number; free_bytes: number; filesystem: string; bus: string; removable: boolean; size_text: string; suggestion: string[] }
export interface SshHostJson { name: string; host: string; user: string; port: number; key: string }
export interface DiskJson { host: string; device: string; model: string; serial: string; size: string; tran: string; wwn: string; by_id: string | null; pool: string | null; vdev: string | null }
export interface SshSeriesRequest { host: string; disks: DiskJson[]; slots: Record<string, string>; chain: boolean; cut_marks: boolean }

// ---------- Einstellungen ----------
export type SettingType = 'bool' | 'int' | 'float' | 'string' | 'choice' | 'path' | 'hotkey' | 'json';
/** Einordnung eines Felds: auf der Seite oder im eingeklappten Abschnitt „Erweitert“. */
export type SettingVisibility = 'sichtbar' | 'erweitert';
export interface SettingField {
  key: string; label: string; type: SettingType; value: unknown; default: unknown; nullable: boolean;
  min?: number; max?: number; step?: number; choices?: { value: string | number | null; label: string }[];
  help?: string; restart?: boolean; experimental?: boolean;
  /** Fehlt in älteren Antworten: dann sichtbar. */
  visibility?: SettingVisibility;
  /** Einheit im Feld (`einstellungen:units.<einheit>`). */
  unit?: string;
}
/** `module`: Einstellungskarte eines Moduls (nur geliefert, wenn es eingeschaltet ist). */
export interface SettingsSection { id: string; title: string; fields: SettingField[]; module?: string | null }
export interface SettingsJson { sections: SettingsSection[]; config_path: string }
export interface TransportChoice { value: string; label: string; experimental: boolean }
export interface SetupStepJson { name: string; ok: boolean; detail: string; hint: string }
export interface SetupJson { ok: boolean; port: string | null; mac: string | null; steps: SetupStepJson[] }
export interface RollJson { tape_id: string; tape_name: string; started: string; length_mm: number; used_mm: number; remaining_mm: number | null; spread_mm: number | null; jobs: number; factor: number; summary: string }
export interface RollsJson { current: RollJson | null; all: RollJson[] }
export interface CalibrationJson { length_factor: number; leader_mm: number; trailer_mm: number; content_offset: number; content_dots: number; verified: string[]; path: string }
/** status je Teil: 'installiert' | 'teilweise' | 'veraltet' | 'nicht installiert' (aus integration.status). lines: Ergebnis von install/uninstall. */
export interface IntegrationJson { status: { context: string; uri: string; autostart: string }; lines: string[] }
export interface ActionJson { kind: string; route: string; note: string }
export type PendingJson =
  | { type: 'lines'; lines: string[] }
  | { type: 'table'; headers: string[]; rows: string[][]; source_name: string }
  | { type: 'image'; name: string; data_b64: string }
  | { type: 'template_file'; name: string; definition: Record<string, unknown> };
export interface BackupJson { name: string; path: string; created: string; size_bytes: number }
export interface DaemonJson { pid: number; version: string; uptime_s: number; web_port: number; home_key: string; log_path: string; app_dir: string }

// ---------- Entwürfe ----------
export interface DraftInfo {
  id: string; title: string; doc_name: string | null; dirty: boolean; updated: string;
  objects: number; order: number; session: string;
}
export interface Draft extends DraftInfo { document: LabelDocumentJson }
export interface DraftListJson { drafts: DraftInfo[]; own: DraftInfo[]; orphaned: DraftInfo[] }
/** Körper für PUT /drafts/{id}; `session` ergänzt der Client selbst. */
export interface DraftPutBody { title: string; doc_name: string | null; document: LabelDocumentJson; dirty: boolean; order: number }
