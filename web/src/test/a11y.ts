/** Barrierefreiheits-Prüfung mit axe-core für Vitest/jsdom. */
import axe from 'axe-core';

export type AxeResult = axe.Result;

/**
 * In jsdom nicht aussagekräftig und deshalb immer aus:
 * - `color-contrast`: jsdom berechnet keine Farben (Kontraste prüft `theme/contrast.ts`).
 * - `region`: Testbäume rendern Ausschnitte ohne Landmarken der Hülle.
 */
const JSDOM_DISABLED = ['color-contrast', 'region'] as const;

/**
 * Weitere bekannte Ausnahmen, jeweils mit Begründung. Leer halten, solange es geht.
 * Eintrag: Regel-ID von axe, z. B. 'aria-allowed-role'.
 */
export const KNOWN_EXCEPTIONS: readonly string[] = [];

// axe erlaubt keine parallelen Läufe im selben Dokument: Aufrufe nacheinander abarbeiten.
let queue: Promise<unknown> = Promise.resolve();

/** Alle axe-Verletzungen unterhalb von `root` (Standard: document.body). */
export function a11yViolations(root?: Element, opts?: { disableRules?: string[] }): Promise<AxeResult[]> {
  const rules: axe.RuleObject = {};
  for (const id of [...JSDOM_DISABLED, ...KNOWN_EXCEPTIONS, ...(opts?.disableRules ?? [])]) {
    rules[id] = { enabled: false };
  }
  const run = queue.then(async () => {
    const result = await axe.run(root ?? document.body, { rules, resultTypes: ['violations'] });
    return result.violations;
  });
  queue = run.catch(() => undefined);
  return run;
}

/** Lesbare Beschreibung: Regel, Hilfe, URL und je Knoten der Ziel-Selektor. */
export function formatViolations(violations: AxeResult[]): string {
  return violations
    .map((v) => {
      const targets = v.nodes.map((n) => `    ${n.target.map(String).join(' ')}`).join('\n');
      return `${v.id} (${v.impact ?? 'unbekannt'}): ${v.help}\n  ${v.helpUrl}\n${targets}`;
    })
    .join('\n');
}

/** Wirft mit Regel, Ziel-Selektor und Hilfe-URL, wenn axe Verletzungen findet. */
export async function expectNoA11yViolations(root?: Element, opts?: { disableRules?: string[] }): Promise<void> {
  const violations = await a11yViolations(root, opts);
  if (violations.length) {
    throw new Error(`Barrierefreiheit: ${violations.length} Verletzung(en)\n${formatViolations(violations)}`);
  }
}
