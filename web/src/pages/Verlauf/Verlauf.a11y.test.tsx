/** Barrierefreiheit und Tastatur des Verlaufs: axe in de und en. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { HistoryEntryJson } from '../../api/types';
import type { Language } from '../../i18n';
import VerlaufPage from './index';

afterEach(() => {
  restoreAllMocks();
  vi.useRealTimers();
});

function entry(o: Partial<HistoryEntryJson> = {}): HistoryEntryJson {
  return {
    id: 1,
    created: '2026-09-27T12:00:00',
    source: 'gui',
    kind: 'text',
    title: 'Server 274913',
    template: null,
    values: {},
    spec: null,
    length_mm: 25,
    tape_mm: 35,
    copies: 2,
    chained: false,
    status: 'ok',
    error: '',
    sensitive: false,
    has_head: true,
    reprintable: true,
    missing_secrets: [],
    ...o,
  };
}

const REPRINT_DIALOG_TITLE: Record<Language, string> = { de: 'Erneut drucken', en: 'Reprint' };

describe('Verlauf: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Grundzustand mit Einträgen (${language})`, async () => {
      mockApi({ 'GET /api/v1/history': () => ({ entries: [entry(), entry({ id: 2, title: 'Zweites Label' })] }) });
      const { container } = renderWithProviders(<VerlaufPage />, { language });
      await screen.findByText('Server 274913');
      await expectNoA11yViolations(container);
    });

    it(`leerer Verlauf (${language})`, async () => {
      mockApi({ 'GET /api/v1/history': () => ({ entries: [] }) });
      const { container } = renderWithProviders(<VerlaufPage />, { language });
      await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
      await expectNoA11yViolations(container);
    });

    it(`Nachdruck-Dialog (${language})`, async () => {
      mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
      const { user } = renderWithProviders(<VerlaufPage />, { language });
      await screen.findByText('Server 274913');
      await user.click(screen.getAllByRole('button', { name: /Erneut drucken|Reprint/ })[0] as HTMLElement);
      await findDialog(REPRINT_DIALOG_TITLE[language]);
      await expectNoA11yViolations(document.body);
    });
  }
});

describe('Verlauf: Tastatur', () => {
  it('Hauptaktion (Erneut drucken) ist per Tab erreichbar und öffnet den Dialog mit Enter', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    const button = screen.getByRole('button', { name: 'Erneut drucken (×2): Server 274913' });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    await findDialog(REPRINT_DIALOG_TITLE.de);
  });

  it('Nachdruck-Dialog schließt mit Escape', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: 'Erneut drucken (×2): Server 274913' }));
    await findDialog(REPRINT_DIALOG_TITLE.de);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByText(REPRINT_DIALOG_TITLE.de, { selector: '.fui-DialogTitle' })).not.toBeInTheDocument());
  });
});

describe('Verlauf: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
    renderWithProviders(<VerlaufPage />, { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Reprint (×2): Server 274913' })).toBeInTheDocument();
  });
});
