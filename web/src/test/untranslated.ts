/**
 * Suche nach unübersetzten deutschen Texten und fest verdrahteten Farben im Quelltext.
 *
 * Nutzung in einem Seiten-Test:
 *   const sources = import.meta.glob('./**\/*.tsx', { query: '?raw', import: 'default', eager: true });
 *   expect(findGermanLiterals(sources as Record<string, string>)).toEqual([]);
 *
 * Bewusst einfache Heuristik ohne vollständigen Parser: Kommentare werden entfernt, String-Literale
 * und JSX-Text zwischen `>` und `<` geprüft. Zeilen mit `// i18n-ignore` und Testdateien zählen nicht.
 */

const LETTER = 'A-Za-zÄÖÜäöüß';
const UMLAUT = /[äöüÄÖÜß]/;
const WORDS = [
  'und',
  'oder',
  'nicht',
  'bitte',
  'wird',
  'werden',
  'keine',
  'kein',
  'drucken',
  'speichern',
  'abbrechen',
  'löschen',
  'schließen',
  'öffnen',
  'einstellungen',
  'vorlage',
  'fehler',
  'zurück',
  'weiter',
  'neu',
  'alle',
  'gedruckt',
  'ungültig',
  'fehlt',
];
const GERMAN_WORD = new RegExp(`(?<![${LETTER}])(?:${WORDS.join('|')})(?![${LETTER}])`, 'i');
const IGNORE_MARK = 'i18n-ignore';

interface Literal {
  line: number;
  /** Inhalt ohne Anführungszeichen. */
  text: string;
  /** Code vor dem Literal (ohne Kommentare), für Import- und t()-Erkennung. */
  before: string;
  template: boolean;
}

interface Scan {
  /** Quelltext mit Kommentaren durch Leerzeichen ersetzt (Zeilen bleiben erhalten). */
  code: string;
  /** Wie `code`, zusätzlich String-Inhalte durch Leerzeichen ersetzt. */
  bare: string;
  literals: Literal[];
}

function blank(s: string): string {
  return s.replace(/[^\n]/g, ' ');
}

/** Kleiner Scanner: trennt Kommentare, String- und Template-Literale vom übrigen Code. */
function scan(source: string): Scan {
  let code = '';
  let bare = '';
  const literals: Literal[] = [];
  let line = 1;
  let i = 0;
  const n = source.length;
  while (i < n) {
    const c = source[i] as string;
    const next = source[i + 1];
    if (c === '/' && next === '/') {
      const end = source.indexOf('\n', i);
      const stop = end === -1 ? n : end;
      const part = source.slice(i, stop);
      code += blank(part);
      bare += blank(part);
      i = stop;
      continue;
    }
    if (c === '/' && next === '*') {
      const end = source.indexOf('*/', i + 2);
      const stop = end === -1 ? n : end + 2;
      const part = source.slice(i, stop);
      code += blank(part);
      bare += blank(part);
      line += (part.match(/\n/g) ?? []).length;
      i = stop;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1;
      let closed = false;
      while (j < n) {
        const d = source[j];
        if (d === '\\') {
          j += 2;
          continue;
        }
        if (d === c) {
          closed = true;
          break;
        }
        // Einfache und doppelte Anführungszeichen enden an der Zeile; sonst war es ein Apostroph im JSX-Text.
        if (d === '\n' && c !== '`') break;
        j += 1;
      }
      if (closed) {
        const part = source.slice(i, j + 1);
        literals.push({ line, text: part.slice(1, -1), before: code, template: c === '`' });
        code += part;
        bare += c + blank(part.slice(1, -1)) + c;
        line += (part.match(/\n/g) ?? []).length;
        i = j + 1;
        continue;
      }
    }
    if (c === '\n') line += 1;
    code += c;
    bare += c;
    i += 1;
  }
  return { code, bare, literals };
}

/** Kleingeschriebene Kennungen ohne Umlaut (Routen, Schlüssel, Enum-Werte wie 'vorlage') sind kein Text. */
const IDENTIFIER = /^[a-z0-9_.:/?=&#-]+$/;

function isGerman(text: string): boolean {
  if (UMLAUT.test(text)) return true;
  return !IDENTIFIER.test(text) && GERMAN_WORD.test(text);
}

function isTestFile(path: string): boolean {
  return /\.test\.[cm]?[jt]sx?$/.test(path);
}

function lineIgnored(lines: string[], line: number): boolean {
  return (lines[line - 1] ?? '').includes(IGNORE_MARK);
}

/** Import-Pfad, Übersetzungsschlüssel oder anderer Text, der nie angezeigt wird. */
function isExcludedContext(before: string): boolean {
  const tail = before.slice(-80);
  if (/(?:^|[\s;}])(?:import|export)\b[^;]*\bfrom\s*$/.test(tail)) return true;
  if (/(?:^|[\s;(])import\s*\(?\s*$/.test(tail)) return true;
  if (/\brequire\s*\(\s*$/.test(tail)) return true;
  if (/(?:^|[^\w$.])(?:i18n\.)?t\s*\(\s*$/.test(tail)) return true;
  if (/\bi18nKey\s*=\s*\{?\s*$/.test(tail)) return true;
  if (/\buseTranslation\s*\(\s*(?:\[\s*)?$/.test(tail)) return true;
  return false;
}

function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

/** Deutsche String- und JSX-Textliterale als „Datei:Zeile: Text“. */
export function findGermanLiterals(sources: Record<string, string>): string[] {
  const hits: string[] = [];
  for (const [file, source] of Object.entries(sources)) {
    if (isTestFile(file) || typeof source !== 'string') continue;
    const lines = source.split('\n');
    const { bare, literals } = scan(source);
    for (const lit of literals) {
      if (lit.template && lit.text.includes('${')) continue;
      if (!isGerman(lit.text)) continue;
      if (lineIgnored(lines, lit.line) || isExcludedContext(lit.before)) continue;
      hits.push(`${file}:${lit.line}: ${oneLine(lit.text)}`);
    }
    // JSX-Text: zwischen `>` (nicht `=>`) und `<`, ohne Ausdrücke in geschweiften Klammern.
    const jsx = /(?<!=)>([^<>{}]+)</g;
    let m: RegExpExecArray | null;
    while ((m = jsx.exec(bare)) !== null) {
      const text = m[1] ?? '';
      if (!text.trim() || !isGerman(text)) continue;
      const offset = m.index + 1 + (text.length - text.trimStart().length);
      const line = bare.slice(0, offset).split('\n').length;
      if (lineIgnored(lines, line)) continue;
      hits.push(`${file}:${line}: ${oneLine(text)}`);
    }
  }
  return hits.sort();
}

const COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g;

/**
 * Fest verdrahtete Farben (Hex, rgb(), hsl()) außerhalb von Kommentaren als „Datei:Zeile: Treffer“.
 * `allow` wird gegen den Dateipfad und die Quelltextzeile geprüft.
 */
export function findHardcodedColors(sources: Record<string, string>, allow: RegExp[] = []): string[] {
  const hits: string[] = [];
  for (const [file, source] of Object.entries(sources)) {
    if (isTestFile(file) || typeof source !== 'string') continue;
    if (allow.some((re) => re.test(file))) continue;
    const lines = source.split('\n');
    const codeLines = scan(source).code.split('\n');
    codeLines.forEach((codeLine, idx) => {
      const original = lines[idx] ?? '';
      if (allow.some((re) => re.test(original))) return;
      for (const m of codeLine.matchAll(COLOR)) hits.push(`${file}:${idx + 1}: ${m[0]}`);
    });
  }
  return hits.sort();
}
