import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { formatDate, formatDateTime, formatMm, formatNumber, formatRelative, localeTag, useFormat } from './format';
import { i18n } from './index';

async function lang(l: 'de' | 'en'): Promise<void> {
  await i18n.changeLanguage(l);
}

describe('format', () => {
  it('localeTag folgt der Sprache', async () => {
    expect(localeTag()).toBe('de-DE');
    expect(localeTag('en')).toBe('en-US');
    await lang('en');
    expect(localeTag()).toBe('en-US');
  });

  it('formatNumber', async () => {
    expect(formatNumber(1234.5)).toBe('1.234,5');
    await lang('en');
    expect(formatNumber(1234.5)).toBe('1,234.5');
  });

  it('formatMm', async () => {
    expect(formatMm(38)).toBe('38 mm');
    expect(formatMm(38.5)).toBe('38,5 mm');
    expect(formatMm(38.25, 2)).toBe('38,25 mm');
    await lang('en');
    expect(formatMm(38.5)).toBe('38.5 mm');
  });

  it('formatDate', async () => {
    expect(formatDate('2026-09-28T10:00:00')).toBe('28.09.2026');
    await lang('en');
    expect(formatDate('2026-09-28T10:00:00')).toBe('9/28/2026');
  });

  it('formatDateTime enthält Datum und Uhrzeit', async () => {
    expect(formatDateTime(new Date(2026, 8, 28, 10, 5))).toBe('28.09.2026, 10:05');
    await lang('en');
    expect(formatDateTime(new Date(2026, 8, 28, 10, 5))).toMatch(/^9\/28\/2026, 10:05\s?AM$/);
  });

  it('ungültiges Datum bleibt als Text stehen', () => {
    expect(formatDate('kein Datum')).toBe('kein Datum');
  });

  it('formatRelative', async () => {
    const now = new Date('2026-09-28T10:00:00');
    const before = new Date(now.getTime() - 5 * 60_000);
    expect(formatRelative(before, now)).toBe('vor 5 Minuten');
    expect(formatRelative(new Date(now.getTime() - 3 * 86_400_000), now)).toBe('vor 3 Tagen');
    expect(formatRelative(new Date(now.getTime() - 400 * 86_400_000), now)).toBe('letztes Jahr');
    await lang('en');
    expect(formatRelative(before, now)).toBe('5 minutes ago');
    expect(formatRelative(new Date(now.getTime() + 2 * 3_600_000), now)).toBe('in 2 hours');
  });

  it('useFormat rendert bei Sprachwechsel neu', async () => {
    const { result } = renderHook(() => useFormat());
    expect(result.current.language).toBe('de');
    expect(result.current.formatNumber(1.5)).toBe('1,5');
    await act(async () => {
      await i18n.changeLanguage('en');
    });
    expect(result.current.language).toBe('en');
    expect(result.current.formatNumber(1.5)).toBe('1.5');
  });
});
