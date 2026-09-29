import { describe, expect, it } from 'vitest';
import { findGermanLiterals, findHardcodedColors } from './untranslated';

function one(source: string): string[] {
  return findGermanLiterals({ 'Seite.tsx': source });
}

describe('findGermanLiterals', () => {
  it('erkennt String-Literale und JSX-Text', () => {
    expect(one("const a = 'Speichern';")).toEqual(['Seite.tsx:1: Speichern']);
    expect(one('const x = (\n  <b>Löschen</b>\n);')).toEqual(['Seite.tsx:2: Löschen']);
    expect(one('const a = "größer";')).toEqual(['Seite.tsx:1: größer']);
    expect(one('const a = `Bitte warten`;')).toEqual(['Seite.tsx:1: Bitte warten']);
    expect(one('<Button title="Vorlage öffnen" />')).toEqual(['Seite.tsx:1: Vorlage öffnen']);
  });

  it('erkennt typische Wörter ohne Umlaut, aber keine Kennungen', () => {
    expect(one("notify('Keine Vorlage gefunden');")).toEqual(['Seite.tsx:1: Keine Vorlage gefunden']);
    expect(one("const by = 'vorlage'; navigate('/einstellungen');")).toEqual([]);
    expect(one("const a = 'Save'; const b = 'undefined';")).toEqual([]);
  });

  it('ignoriert Kommentare, Schlüssel, Importe und markierte Zeilen', () => {
    expect(one('// Kommentar mit Löschen\nconst a = 1;')).toEqual([]);
    expect(one('/* Block mit Löschen\n und mehr */ const a = 1;')).toEqual([]);
    expect(one("const a = t('common:actions.delete');")).toEqual([]);
    expect(one("const a = i18n.t('schnelldruck:übersicht');")).toEqual([]);
    expect(one("const { t } = useTranslation('einstellungen');")).toEqual([]);
    expect(one('<Trans i18nKey="vorlagen:löschen.frage" />')).toEqual([]);
    expect(one("import x from './Übersicht';")).toEqual([]);
    expect(one("const L = lazy(() => import('./Übersicht'));")).toEqual([]);
    expect(one("const a = 'Speichern'; // i18n-ignore")).toEqual([]);
    expect(one('const a = `${n} Löschen`;')).toEqual([]);
    expect(one("const url = 'http://x/y'; const b = 'Schließen';")).toEqual(['Seite.tsx:1: Schließen']);
  });

  it('Apostroph im JSX-Text bricht die Erkennung nicht', () => {
    expect(one("<p>Don't</p>\nconst a = 'Zurück';")).toEqual(['Seite.tsx:2: Zurück']);
  });

  it('überspringt Testdateien und meldet Datei:Zeile', () => {
    expect(findGermanLiterals({ 'a.test.tsx': "const a = 'Löschen';" })).toEqual([]);
    expect(findGermanLiterals({ 'b.tsx': "\n\nconst a = 'Löschen';" })).toEqual(['b.tsx:3: Löschen']);
  });
});

describe('findHardcodedColors', () => {
  it('findet Hex, rgba und hsl', () => {
    expect(findHardcodedColors({ 'a.tsx': "const c = '#ff0000';" })).toEqual(['a.tsx:1: #ff0000']);
    expect(findHardcodedColors({ 'a.tsx': 'const c = "rgba(0,0,0,.5)";' })).toEqual(['a.tsx:1: rgba(']);
    expect(findHardcodedColors({ 'a.tsx': "const c = 'hsl(0 0% 0%)';" })).toEqual(['a.tsx:1: hsl(']);
  });

  it('ignoriert Tokens, Kommentare und erlaubte Stellen', () => {
    expect(findHardcodedColors({ 'a.tsx': 'const c = tokens.colorNeutralForeground1;' })).toEqual([]);
    expect(findHardcodedColors({ 'a.tsx': '// Farbe #ff0000 war früher hart kodiert' })).toEqual([]);
    expect(findHardcodedColors({ 'a.tsx': "const c = '#fff'; // Bandfarbe" }, [/Bandfarbe/])).toEqual([]);
    expect(findHardcodedColors({ 'theme/x.ts': "const c = '#fff';" }, [/^theme\//])).toEqual([]);
  });
});
