/** Prüft alle Namespaces unter web/src/locales (gilt automatisch für jeden neuen Namespace). */
import { describe, expect, it } from 'vitest';
import { namespaces, resources } from './resources';

/** Alle stabilen Fehlercodes: die Server-Codes (mit decoder.unavailable und module.disabled) und die beiden Client-Codes. */
export const ERROR_CODES = [
  'printer.busy',
  'file.locked',
  'print.incomplete',
  'printer.unreachable',
  'port.busy',
  'port.missing',
  'bluetooth.lost',
  'printer.not_paired',
  'transport.error',
  'ipc.error',
  'template.invalid',
  'document.invalid',
  'protocol.error',
  'font.missing',
  'secret.missing',
  'label.not_printable',
  'value.invalid',
  'request.invalid',
  'not_found',
  'auth.required',
  'auth.forbidden',
  'method.not_allowed',
  'conflict',
  'too_large',
  'rate_limited',
  'http.error',
  'integration.token_missing',
  'integration.not_configured',
  'integration.unreachable',
  'integration.auth_failed',
  'integration.upstream',
  'update.not_installed',
  'update.no_trusted_key',
  'update.source_invalid',
  'update.source_unreachable',
  'update.signature_invalid',
  'update.checksum_mismatch',
  'update.download_failed',
  'update.busy',
  'update.apply_failed',
  'decoder.unavailable',
  'module.disabled',
  'aborted',
  'internal',
  'client.offline',
  'client.bad_response',
] as const;

function flatten(obj: unknown, prefix = '', out: Record<string, unknown> = {}): Record<string, unknown> {
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      flatten(v, prefix ? `${prefix}.${k}` : k, out);
    }
  } else {
    out[prefix] = obj;
  }
  return out;
}

function table(lang: string, ns: string): Record<string, unknown> {
  return flatten((resources[lang] as Record<string, unknown> | undefined)?.[ns] ?? {});
}

function placeholders(value: string): string[] {
  return [...value.matchAll(/\{\{\s*([^}\s]+)\s*\}\}/g)].map((m) => m[1] ?? '').sort();
}

const LANGS = ['de', 'en'] as const;

describe('locales', () => {
  it('es gibt genau die Sprachen de und en', () => {
    expect(Object.keys(resources).sort()).toEqual([...LANGS]);
  });

  for (const ns of namespaces) {
    describe(`Namespace ${ns}`, () => {
      const de = table('de', ns);
      const en = table('en', ns);

      it('gleiche Schlüssel in de und en', () => {
        const missingEn = Object.keys(de).filter((k) => !(k in en));
        const missingDe = Object.keys(en).filter((k) => !(k in de));
        expect({ fehltInEn: missingEn, fehltInDe: missingDe }).toEqual({ fehltInEn: [], fehltInDe: [] });
      });

      it('keine leeren Werte, nur Texte', () => {
        const bad = LANGS.flatMap((l) =>
          Object.entries(table(l, ns))
            .filter(([, v]) => typeof v !== 'string' || v.trim() === '')
            .map(([k]) => `${l}:${k}`),
        );
        expect(bad).toEqual([]);
      });

      it('keine Gedankenstriche', () => {
        const bad = LANGS.flatMap((l) =>
          Object.entries(table(l, ns))
            .filter(([, v]) => typeof v === 'string' && (/[\u2013\u2014]/.test(v) || /\S - \S/.test(v)))
            .map(([k]) => `${l}:${k}`),
        );
        expect(bad).toEqual([]);
      });

      it('gleiche Platzhalter je Schlüssel', () => {
        const bad = Object.keys(de).filter((k) => {
          const a = de[k];
          const b = en[k];
          if (typeof a !== 'string' || typeof b !== 'string') return false;
          return placeholders(a).join(',') !== placeholders(b).join(',');
        });
        expect(bad).toEqual([]);
      });

      it('Plural-Paare _one/_other vollständig', () => {
        const bad = LANGS.flatMap((l) => {
          const keys = Object.keys(table(l, ns));
          return keys
            .filter((k) => k.endsWith('_one') || k.endsWith('_other'))
            .filter((k) => {
              const base = k.replace(/_(one|other)$/, '');
              return !keys.includes(`${base}_one`) || !keys.includes(`${base}_other`);
            })
            .map((k) => `${l}:${k}`);
        });
        expect(bad).toEqual([]);
      });
    });
  }

  it('errors enthält genau die festgelegten Fehlercodes, je mit title und hint', () => {
    expect(ERROR_CODES).toHaveLength(46);
    for (const lang of LANGS) {
      const flat = table(lang, 'errors');
      const expected = ERROR_CODES.flatMap((c) => [`${c}.title`, `${c}.hint`]).sort();
      expect(Object.keys(flat).sort()).toEqual(expected);
    }
  });
});
