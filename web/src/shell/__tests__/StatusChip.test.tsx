/** Kompakter Statuschip: ohne Transportpfad, Englisch aus dem Zustand gebaut. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import type { StatusJson } from '../../api/types';
import { i18n } from '../../i18n';
import { fixtures, LocationProbe, mockApi, renderWithProviders, setTestLanguage } from '../../test/utils';
import { compactChipText } from '../StatusChip';

const CONNECTED: StatusJson = {
  report: {
    state: { state: 'verbunden', transport: 'file:C:\\Users\\x\\AppData\\Local\\Temp\\p12\\job.bin', last_error: null, leased: false },
    status: {
      answered: true,
      values: { battery: { value: 75, text: '75 %', verified: true, raw: '' } },
      unknown: [],
      raw: '',
    },
    checked_at: '2026-09-28T10:00:00',
  },
  view: {
    chip: 'P12 · verbunden (file:C:\\Users\\x\\AppData\\Local\\Temp\\p12\\job.bin) · Akku 75 %',
    role: 'success',
    title: 'Tapesmith: verbunden',
    detail: 'Verbindung: verbunden',
    tooltip: 'verbunden (file:C:\\Users\\x\\AppData\\Local\\Temp\\p12\\job.bin) · Akku 75 %, Status gerade eben',
  },
};

const t = (key: string, opts?: Record<string, unknown>) => String(i18n.t(`shell:${key}`, opts));

describe('compactChipText', () => {
  it('Deutsch: Server-Text ohne Transportpfad', () => {
    expect(compactChipText(CONNECTED, t)).toBe('P12 · verbunden · Akku 75 %');
  });

  it('Englisch: aus Zustand und bestätigten Werten', () => {
    setTestLanguage('en');
    expect(compactChipText(CONNECTED, t)).toBe('P12 · connected · Battery 75 %');
  });

  it('unbekannter Zustand: Server-Text', () => {
    setTestLanguage('en');
    expect(compactChipText(fixtures.statusJson, t)).toBe('Bereit');
  });
});

describe('StatusChip', () => {
  it('zeigt den kompakten Text, der volle steht im Namen nicht doppelt', async () => {
    mockApi({ 'GET /api/v1/status': () => CONNECTED }, { quiet: true });
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    const chip = await screen.findByTestId('status-chip');
    await waitFor(() => expect(chip).toHaveTextContent('P12 · verbunden · Akku 75 %'));
    expect(chip).toHaveAccessibleName('Druckerstatus: P12 · verbunden · Akku 75 %');
    expect(chip.textContent).not.toContain('job.bin');
  });
});
