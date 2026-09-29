import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, screen } from '@testing-library/react';
import { ErrorMessage, useErrorText } from '../ErrorMessage';
import { ApiError } from '../../api/client';
import { i18n } from '../../i18n';
import { renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';

function timeout(): ApiError {
  return new ApiError(503, 'ConnectTimeout', 'Zeitüberschreitung', 'Hinweis', 5, null, 'printer.unreachable');
}

describe('ErrorMessage', () => {
  it('de: Titel aus dem Code, Server-Meldung und Server-Hinweis', () => {
    renderWithProviders(<ErrorMessage error={timeout()} />);
    expect(screen.getByText('Drucker nicht erreichbar')).toBeInTheDocument();
    expect(screen.getByText('Zeitüberschreitung')).toBeInTheDocument();
    expect(screen.getByText('Hinweis')).toBeInTheDocument();
  });

  it('en: englischer Titel aus dem Code, Meldung und Hinweis kommen übersetzt vom Dienst', () => {
    const err = new ApiError(503, 'ConnectTimeout', 'Timed out', 'Check the printer', 5, null, 'printer.unreachable');
    renderWithProviders(<ErrorMessage error={err} />, { language: 'en' });
    expect(screen.getByText('Printer unreachable')).toBeInTheDocument();
    expect(screen.getByText('Timed out')).toBeInTheDocument();
    expect(screen.getByText('Check the printer')).toBeInTheDocument();
  });

  it('ohne Hinweis des Dienstes gilt der Hinweis des Codes', () => {
    const err = new ApiError(503, 'ConnectTimeout', 'Timed out', '', 5, null, 'printer.unreachable');
    renderWithProviders(<ErrorMessage error={err} />, { language: 'en' });
    expect(screen.getByText(/Is the printer off or asleep\?/)).toBeInTheDocument();
  });

  it('„Erneut versuchen“ ruft onRetry', async () => {
    const onRetry = vi.fn();
    const { user } = renderWithProviders(<ErrorMessage error={timeout()} onRetry={onRetry} />);
    await user.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('ohne onRetry kein Knopf', () => {
    renderWithProviders(<ErrorMessage error={timeout()} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('Offline-Fehler des Clients zeigt den Titel nur einmal', () => {
    const offline = new ApiError(0, 'Offline', 'Druckdienst nicht erreichbar', 'Läuft der Druckdienst?', 1, null, 'client.offline');
    renderWithProviders(<ErrorMessage error={offline} />);
    expect(screen.getAllByText('Druckdienst nicht erreichbar')).toHaveLength(1);
  });

  it('Englisch: Fehler des Clients (Offline, kaputte Antwort) in der Sprache der Oberfläche', async () => {
    await i18n.changeLanguage('en');
    const offline = new ApiError(0, 'Offline', i18n.t('errors:client.offline.title'), i18n.t('errors:client.offline.hint'), 1, null, 'client.offline');
    const broken = new ApiError(502, 'Network', i18n.t('common:errors.badStatus', { status: 502 }), '', 1, null, 'client.bad_response');
    renderWithProviders(
      <>
        <ErrorMessage error={offline} />
        <ErrorMessage error={broken} />
      </>,
      { language: 'en' },
    );
    expect(screen.getAllByText('Print service unavailable')).toHaveLength(1);
    expect(screen.getByText('Unexpected response from the print service')).toBeInTheDocument();
    expect(screen.getByText('Unexpected response from the print service (HTTP 502)')).toBeInTheDocument();
    expect(screen.queryByText(/Druckdienst/)).toBeNull();
    expect(screen.queryByText(/Läuft/)).toBeNull();
  });

  it('allgemeiner Code: Titel der Seite gewinnt; kein ApiError: interner Fehler', () => {
    renderWithProviders(
      <>
        <ErrorMessage error={new ApiError(500, 'X', 'Kaputt')} title="Speichern fehlgeschlagen" />
        <ErrorMessage error={new Error('Absturz')} />
      </>,
    );
    expect(screen.getByText('Speichern fehlgeschlagen')).toBeInTheDocument();
    expect(screen.getByText('Kaputt')).toBeInTheDocument();
    expect(screen.getByText('Fehler')).toBeInTheDocument();
    expect(screen.getByText('Absturz')).toBeInTheDocument();
  });

  for (const language of ['de', 'en'] as const) {
    it(`ohne axe-Verletzungen (${language})`, async () => {
      const { container } = renderWithProviders(
        <main>
          <ErrorMessage error={timeout()} onRetry={() => {}} />
        </main>,
        { language },
      );
      await expectNoA11yViolations(container);
    });
  }
});

describe('useErrorText', () => {
  it('liefert Titel, Meldung, Hinweis und Code und folgt der Sprache', async () => {
    const { result } = renderHook(() => useErrorText());
    expect(result.current(timeout())).toEqual({
      title: 'Drucker nicht erreichbar',
      message: 'Zeitüberschreitung',
      hint: 'Hinweis',
      code: 'printer.unreachable',
    });
    await act(async () => {
      await i18n.changeLanguage('en');
    });
    expect(result.current(timeout()).title).toBe('Printer unreachable');
    expect(result.current('kaputt')).toMatchObject({ title: 'Error', message: 'kaputt', code: 'internal' });
  });
});
