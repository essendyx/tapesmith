/** Barrierefreiheit und Tastatur der Seite Kabel: axe in de und en, Reiter, Fehler. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { MockResponse, mockApi, renderWithProviders, type MockHandler } from '../../test/utils';
import type { Language } from '../../i18n';
import type { NetboxPreviewJson } from './types';
import KabelPage from './index';

function previewResponse(): NetboxPreviewJson {
  return {
    headers: ['ID', 'Label', 'Side A', 'Termination A', 'Side B', 'Termination B', 'Type'],
    mapping: { kabel_id: 'Label', quelle: 'Side A', ziel: 'Side B', kabeltyp: 'Type' },
    rows: [{ kabel_id: 'K-100', quelle: 'SW1', ziel: 'pmx10', kabeltyp: 'Cat6', farbe: '', laenge: '', neu: false }],
    duplicates: [],
    warnings: [],
    preview_only: true,
  };
}

function routes(extra: Record<string, MockHandler> = {}): Record<string, MockHandler> {
  return { 'GET /api/v1/homelab/kabel/register': () => ({ entries: [] }), ...extra };
}

const HEADING = { de: 'Kabel', en: 'Cables' } as const;
const SCHEMA_TAB = { de: 'ID-Schema', en: 'ID scheme' } as const;
const REGISTER_TAB = { de: 'Register', en: 'Register' } as const;

describe.each(['de', 'en'] as Language[])('Seite Kabel: axe (%s)', (language) => {
  it('Grundzustand (NetBox-Import) ohne Befund', async () => {
    mockApi(routes());
    const { container } = renderWithProviders(<KabelPage />, { route: '/homelab/kabel', language });
    await screen.findByRole('heading', { name: HEADING[language] });
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (Register) ohne Befund', async () => {
    mockApi(routes());
    const { user, container } = renderWithProviders(<KabelPage />, { route: '/homelab/kabel', language });
    await user.click(await screen.findByRole('tab', { name: REGISTER_TAB[language] }));
    await screen.findByText(language === 'de' ? 'Noch keine Kabel-ID vergeben' : 'No cable ID assigned yet');
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand (ID-Schema) ohne Befund', async () => {
    mockApi(
      routes({
        'POST /api/v1/homelab/kabel/ids': () =>
          new MockResponse(422, { error: { kind: 'ValueError', message: 'Muster ungültig', hint: '', exit_code: 1, details: null } }),
      }),
    );
    const { user, container } = renderWithProviders(<KabelPage />, { route: '/homelab/kabel', language });
    await user.click(await screen.findByRole('tab', { name: SCHEMA_TAB[language] }));
    await screen.findByText('Muster ungültig');
    await expectNoA11yViolations(container);
  });

  it('gefüllte NetBox-Vorschau ohne Befund', async () => {
    mockApi(routes({ 'POST /api/v1/homelab/kabel/netbox': () => previewResponse() }));
    const { user, container } = renderWithProviders(<KabelPage />, { route: '/homelab/kabel', language });
    const fileInput = (await screen.findByLabelText(language === 'de' ? 'NetBox-CSV hochladen' : 'Upload NetBox CSV')) as HTMLInputElement;
    const file = new File(['ID,Label,Side A\n1,K-100,SW1'], 'cables-export.csv', { type: 'text/csv' });
    await user.upload(fileInput, file);
    await screen.findByText('SW1');
    await expectNoA11yViolations(container);
  });
});

describe('Seite Kabel: Tastatur', () => {
  it('Reiter „ID-Schema" per Tab erreichbar, per Enter aktiviert er sich', async () => {
    mockApi(routes());
    const { user } = renderWithProviders(<KabelPage />, { route: '/homelab/kabel' });
    const tab = await screen.findByRole('tab', { name: SCHEMA_TAB.de });
    tab.focus();
    expect(tab).toHaveFocus();
    await user.keyboard('{Enter}');
    await screen.findByLabelText('Muster');
  });
});
