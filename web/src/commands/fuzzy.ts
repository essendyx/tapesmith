/** Unscharfe Suche, Port von `tapesmith/commandreg.py` (`fold`, `_score`). */
import { isEnabled, type CommandDef } from './registry';

const AEOU: [string, string][] = [
  ['ae', 'a'],
  ['oe', 'o'],
  ['ue', 'u'],
];

/** Kleinschreibung, `ß` zu `ss`, Umlaute/Akzente entfernt (NFKD). `ae`/`oe`/`ue` bleiben erhalten. */
export function fold(text: string): string {
  return text
    .toLocaleLowerCase('de-DE')
    .replace(/ß/g, 'ss')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '');
}

function foldVariants(text: string): string[] {
  const folded = fold(text);
  let variant = folded;
  for (const [src, dst] of AEOU) variant = variant.split(src).join(dst);
  return variant === folded ? [folded] : [folded, variant];
}

function initials(words: string[]): string {
  return words
    .filter((w) => w)
    .map((w) => w[0])
    .join('');
}

function isSubsequence(query: string, text: string): boolean {
  let pos = 0;
  for (const ch of query) {
    const found = text.indexOf(ch, pos);
    if (found < 0) return false;
    pos = found + 1;
  }
  return true;
}

export function fuzzyScore(query: string, cmd: CommandDef): number {
  let best = 0;
  const title = fold(cmd.title);
  const words = title.split(/\s+/).filter(Boolean);
  const keywords = (cmd.keywords ?? []).map(fold);

  for (const q of foldVariants(query.trim())) {
    if (!q) continue;
    if (keywords.includes(q)) best = Math.max(best, 100);
    else if (title.startsWith(q)) best = Math.max(best, 80);
    else if (keywords.some((k) => k.startsWith(q))) best = Math.max(best, 70);
    else if (words.some((w) => w.startsWith(q))) best = Math.max(best, 60);
    else if (title.includes(q)) best = Math.max(best, 40);
    else if (keywords.some((k) => k.includes(q))) best = Math.max(best, 30);
    else if (initials(words).startsWith(q)) best = Math.max(best, 20);
    else if (isSubsequence(q, title)) best = Math.max(best, 10);
  }
  return best;
}

/** Treffer absteigend nach Punktzahl, bei Gleichstand nach Titel. Leere Suche: alle, nach Gruppe und Titel. */
export function searchCommands(query: string, commands: CommandDef[], limit = 50): CommandDef[] {
  const enabled = commands.filter(isEnabled);
  const q = query.trim();
  if (!q) {
    return [...enabled]
      .sort((a, b) => a.group.localeCompare(b.group, 'de') || a.title.localeCompare(b.title, 'de'))
      .slice(0, limit);
  }
  return enabled
    .map((cmd) => ({ cmd, score: fuzzyScore(q, cmd) }))
    .filter((e) => e.score > 0)
    .sort((a, b) => b.score - a.score || a.cmd.title.localeCompare(b.cmd.title, 'de'))
    .slice(0, limit)
    .map((e) => e.cmd);
}
