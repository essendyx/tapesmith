/** Barrierefreiheit und Tastatur der Seite SnScan: axe in de/en, Tastatur. */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import type { CodescanResultJson } from './types';
import SnScanPage from '.';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    prepareImage: vi.fn(async () => 'ZmFrZS1iaWxk'),
  };
});

function file(): File {
  return new File(['fake-bild'], 'aufkleber.png', { type: 'image/png' });
}

const RESULT: CodescanResultJson = {
  width: 800,
  height: 600,
  hits: [{ text: 'S/N ABC123456', format: 'Code128', position: [10, 10, 100, 40] }],
  candidates: [{ serial: 'ABC123456', score: 90, reason: 'Präfix S/N, Code128', text: 'S/N ABC123456', format: 'Code128' }],
  best: 'ABC123456',
  shortened: '123456',
};

const CHOOSE_LABEL = { de: 'Foto des Aufklebers auswählen', en: 'Choose photo of the label' } as const;

async function uploadPhoto(user: ReturnType<typeof renderWithProviders>['user'], language: Language): Promise<void> {
  const input = screen.getByLabelText(CHOOSE_LABEL[language], { selector: 'input' });
  await user.upload(input, file());
}

describe.each(['de', 'en'] as Language[])('SnScan a11y (%s)', (language) => {
  it('Grundzustand ohne axe-Befund', async () => {
    mockApi({ 'POST /api/v1/homelab/codescan': () => RESULT });
    const { container, user } = renderWithProviders(<SnScanPage />, { language, route: '/homelab/sn-scan' });
    await uploadPhoto(user, language);
    await screen.findByText('ABC123456');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (keine Codes) ohne axe-Befund', async () => {
    mockApi({ 'POST /api/v1/homelab/codescan': () => ({ width: 400, height: 300, hits: [], candidates: [], best: null, shortened: null }) });
    const { container, user } = renderWithProviders(<SnScanPage />, { language, route: '/homelab/sn-scan' });
    await uploadPhoto(user, language);
    await screen.findByText(language === 'de' ? 'Keine Codes gefunden' : 'No codes found');
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand ohne axe-Befund', async () => {
    mockApi({
      'POST /api/v1/homelab/codescan': () =>
        new MockResponse(422, { error: { kind: 'ValueError', message: 'Datei ist kein lesbares Bild', hint: '', exit_code: 1, details: null } }),
    });
    const { container, user } = renderWithProviders(<SnScanPage />, { language, route: '/homelab/sn-scan' });
    await uploadPhoto(user, language);
    await screen.findByText('Datei ist kein lesbares Bild');
    await expectNoA11yViolations(container);
  });
});

describe('SnScan Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    renderWithProviders(<SnScanPage />, { language: 'en', route: '/homelab/sn-scan' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Serial number scan' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Take photo or choose image' })).toBeInTheDocument();
  });
});

describe('SnScan Tastatur', () => {
  it('Hauptaktion per Tastatur erreichbar und auslösbar (öffnet die Dateiauswahl)', async () => {
    const { user } = renderWithProviders(<SnScanPage />, { route: '/homelab/sn-scan' });
    const main = screen.getByRole('button', { name: 'Foto aufnehmen oder Bild wählen' });
    const input = screen.getByLabelText('Foto des Aufklebers auswählen', { selector: 'input' });
    const clickSpy = vi.spyOn(input, 'click');
    main.focus();
    expect(main).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(clickSpy).toHaveBeenCalled();
  });
});
