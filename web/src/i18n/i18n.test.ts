import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { currentLanguage, i18n, initI18n, LANGUAGES, resolveLanguage, setServiceLanguage, translateOr, useLanguageSync } from './index';
import { namespaces, resources } from './resources';

describe('resolveLanguage', () => {
  it('auto folgt der Sprache des Dienstes (Windows-Anzeigesprache), nicht dem Browser', () => {
    expect(resolveLanguage('auto', ['de-DE'], 'en')).toBe('en');
    expect(resolveLanguage('auto', ['en-US'], 'de')).toBe('de');
    expect(resolveLanguage(null, ['en-US'], 'de')).toBe('de');
  });
  it('ohne Meldung des Dienstes die erste passende Browser-Sprache', () => {
    expect(resolveLanguage('auto', ['en-US', 'de'], null)).toBe('en');
    expect(resolveLanguage('auto', ['fr-FR', 'de'], undefined)).toBe('de');
  });
  it('jede andere Sprache wird Englisch', () => {
    expect(resolveLanguage('auto', ['fr-FR'], null)).toBe('en');
    expect(resolveLanguage(undefined, [], null)).toBe('en');
    expect(resolveLanguage('auto', [], 'fr')).toBe('en');
  });
  it('feste Einstellung gewinnt', () => {
    expect(resolveLanguage('de', ['en-US'], 'en')).toBe('de');
    expect(resolveLanguage('en', ['de-DE'], 'de')).toBe('en');
  });
  it('setServiceLanguage gilt für spätere Aufrufe ohne Angabe', () => {
    setServiceLanguage('en');
    expect(resolveLanguage('auto', ['de-DE'])).toBe('en');
    setServiceLanguage(null);
    expect(resolveLanguage('auto', ['de-DE'])).toBe('de');
  });
  it('ohne Liste gilt navigator.languages (im Test Deutsch)', () => {
    expect(resolveLanguage('auto')).toBe('de');
  });
});

describe('initI18n', () => {
  it('ist idempotent und ändert beim zweiten Aufruf nur die Sprache', () => {
    expect(() => initI18n({ language: 'de', test: true })).not.toThrow();
    initI18n({ language: 'en' });
    expect(currentLanguage()).toBe('en');
    initI18n({ language: 'de' });
    expect(currentLanguage()).toBe('de');
    expect(LANGUAGES).toEqual(['de', 'en']);
  });

  it('übersetzt gemeinsame Texte in beiden Sprachen', async () => {
    expect(i18n.t('common:actions.save')).toBe('Speichern');
    await i18n.changeLanguage('en');
    expect(i18n.t('common:actions.save')).toBe('Save');
    expect(i18n.t('actions.cancel')).toBe('Cancel');
  });

  it('fehlender Schlüssel wirft im Testmodus', () => {
    expect(() => i18n.t('common:gibtEsNicht')).toThrow(/fehlender Schlüssel/);
  });

  it('translateOr liefert den Rückfall ohne Fehler', () => {
    expect(translateOr('common:gibtEsNicht', 'X')).toBe('X');
    expect(translateOr('common:actions.save', 'X')).toBe('Speichern');
    expect(translateOr('common:units.mm', 'X', { value: 3 })).toBe('3 mm');
  });

  it('Namespaces enthalten common und errors, Ressourcen je Sprache', () => {
    expect(namespaces).toEqual(expect.arrayContaining(['common', 'errors']));
    expect(Object.keys(resources).sort()).toEqual(['de', 'en']);
  });
});

describe('useLanguageSync', () => {
  it('setzt Sprache und <html lang>', () => {
    const { rerender } = renderHook((p: { s: 'auto' | 'de' | 'en' | null | undefined }) => useLanguageSync(p.s), {
      initialProps: { s: 'en' },
    });
    expect(document.documentElement.lang).toBe('en');
    expect(currentLanguage()).toBe('en');
    rerender({ s: 'auto' });
    expect(document.documentElement.lang).toBe('de');
    expect(currentLanguage()).toBe('de');
  });

  it('auto übernimmt die vom Dienst gemeldete Sprache', () => {
    const { rerender } = renderHook(
      (p: { s: 'auto' | 'de' | 'en'; service: string | null }) => useLanguageSync(p.s, p.service),
      { initialProps: { s: 'auto', service: 'en' } },
    );
    expect(currentLanguage()).toBe('en');
    rerender({ s: 'de', service: 'en' });
    expect(currentLanguage()).toBe('de');
    rerender({ s: 'auto', service: 'de' });
    expect(currentLanguage()).toBe('de');
    setServiceLanguage(null);
  });

  it('undefined (App-Info noch nicht geladen) ändert die Sprache nicht', async () => {
    await i18n.changeLanguage('en');
    renderHook(() => useLanguageSync(undefined));
    expect(currentLanguage()).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });
});
