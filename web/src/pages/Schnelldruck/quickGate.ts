/**
 * Fehldruckschutz des Schnelldrucks, Port von `tapesmith.gui.quickgate`
 * (`QuickPrintGate`/`normalize_paste`). Reine Logik, ohne Fluent- oder DOM-Abhängigkeit, damit
 * Schnelldruck und Kompakt (`../Kompakt`) dieselbe Entscheidung treffen wie die Qt-Vorgänger.
 */

export const MAX_LINES = 3;

/**
 * Gründe für eine Ignorieren-Entscheidung als Kennung; die Anzeige (immer als Text, nie nur Farbe)
 * übersetzt `gateMessages` über `schnelldruck:gate.<kennung>`.
 */
export const REASONS = {
  empty: 'empty',
  busy: 'busy',
  stale: 'stale',
  invalid: 'invalid',
  review: 'review',
  debounce: 'debounce',
  repeat: 'repeat',
  lines: 'lines',
} as const;

export type GateAction = 'print' | 'newline' | 'ignore';
export type KeyKind = 'enter' | 'ctrl_enter' | 'shift_enter';

export interface GateDecision {
  action: GateAction;
  reason: string;
}

export interface PasteResult {
  lines: string[];
  multiline: boolean;
  error: string | null;
}

const PRINT_DECISION: GateDecision = { action: 'print', reason: '' };
const NEWLINE_DECISION: GateDecision = { action: 'newline', reason: '' };

function ignore(reason: string): GateDecision {
  return { action: 'ignore', reason };
}

/**
 * Normalisiert eingefügten Text: einheitliche Zeilenumbrüche (CRLF, CR, U+2028, U+2029), Tabs als
 * Leerzeichen, Steuerzeichen entfernt, keine führenden/abschließenden Leerzeilen.
 */
// Als Code-Punkte (statt als wörtliche Zeichen im Quelltext), weil U+2028/U+2029 sonst als
// Zeilenterminator des JS-Parsers selbst wirken.
const LINE_SEPARATOR = String.fromCharCode(0x2028);
const PARAGRAPH_SEPARATOR = String.fromCharCode(0x2029);

export function normalizePaste(text: string, currentLines = 1): PasteResult {
  let t = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  t = t.split(LINE_SEPARATOR).join('\n').split(PARAGRAPH_SEPARATOR).join('\n');
  t = t.replace(/\t/g, ' ');
  t = Array.from(t)
    .filter((ch) => ch === '\n' || (ch.codePointAt(0) ?? 0) >= 0x20)
    .join('');
  t = t.replace(/^\n+/, '').replace(/\n+$/, '');
  const lines = t.split('\n');
  const multiline = lines.length > 1;
  const error = currentLines - 1 + lines.length > MAX_LINES ? REASONS.lines : null;
  return { lines, multiline, error };
}

export interface QuickGateOptions {
  ctrlEnterOnly?: boolean;
  minIntervalS?: number;
  /** Injizierbare Uhr in Sekunden (Standard: `performance.now() / 1000`), für Entprellungstests. */
  clock?: () => number;
}

function defaultClock(): number {
  return performance.now() / 1000;
}

/** Zustand des Fehldruckschutzes für ein Eingabefeld (Schnelldruck und Kompakt teilen sich die Klasse). */
export class QuickGate {
  ctrlEnterOnly: boolean;
  private readonly minIntervalS: number;
  private readonly clock: () => number;
  private gateRevision = 0;
  private previewRevision: number | null = null;
  private previewOk = false;
  private busy = false;
  private review = false;
  private lastPrint: number | null = null;

  constructor(opts: QuickGateOptions = {}) {
    this.ctrlEnterOnly = opts.ctrlEnterOnly ?? false;
    this.minIntervalS = opts.minIntervalS ?? 1;
    this.clock = opts.clock ?? defaultClock;
  }

  get revision(): number {
    return this.gateRevision;
  }

  /** Vorschau passt zur aktuellen Revision und war fehlerfrei. */
  get previewCurrent(): boolean {
    return this.previewRevision === this.gateRevision && this.previewOk;
  }

  edited(): number {
    this.gateRevision += 1;
    return this.gateRevision;
  }

  pasted(text: string, currentLines = 1): PasteResult {
    const result = normalizePaste(text, currentLines);
    if (result.error !== null) return result;
    this.gateRevision += 1;
    if (result.multiline) this.review = true;
    return result;
  }

  previewReady(revision: number, ok: boolean): void {
    if (revision !== this.gateRevision) return;
    this.previewRevision = revision;
    this.previewOk = ok;
  }

  setBusy(busy: boolean): void {
    this.busy = busy;
  }

  markPrinted(): void {
    this.lastPrint = this.clock();
  }

  canPrint(text: string): GateDecision {
    if (text.trim() === '') return ignore(REASONS.empty);
    if (this.busy) return ignore(REASONS.busy);
    if (this.review) {
      this.review = false;
      return ignore(REASONS.review);
    }
    if (this.previewRevision !== this.gateRevision) return ignore(REASONS.stale);
    if (!this.previewOk) return ignore(REASONS.invalid);
    if (this.lastPrint !== null && this.clock() - this.lastPrint < this.minIntervalS) return ignore(REASONS.debounce);
    return PRINT_DECISION;
  }

  key(kind: KeyKind, opts: { text: string; autoRepeat?: boolean }): GateDecision {
    if (opts.autoRepeat) return ignore(REASONS.repeat);
    if (kind === 'shift_enter' || (kind === 'enter' && this.ctrlEnterOnly)) {
      if (opts.text.split('\n').length < MAX_LINES) return NEWLINE_DECISION;
      return ignore(REASONS.lines);
    }
    // ENTER (ohne ctrlEnterOnly) oder CTRL_ENTER: Druckversuch.
    return this.canPrint(opts.text);
  }
}
