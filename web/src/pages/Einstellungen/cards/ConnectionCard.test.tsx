import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { MockResponse, mockApi, renderWithProviders } from '../../../test/utils';
import { baseSettingsRoutes, makeSettings } from '../testFixtures';
import type { SettingsJson } from '../../../api/types';
import EinstellungenPage from '../index';

describe('Karte Drucker und Verbindung', () => {
  it('zeigt Schritte aus SetupJson mit Symbolen', async () => {
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/settings/setup': () => ({
          ok: true,
          port: 'COM5',
          mac: null,
          steps: [
            { name: 'Verbinden', ok: true, detail: 'Verbunden mit COM5', hint: '' },
            { name: 'Testlabel', ok: false, detail: 'Kein Papier', hint: 'Band prüfen' },
          ],
        }),
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const card = document.getElementById('verbindung') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Drucker suchen und testen' }));

    expect(await within(card).findByText('Verbinden', { exact: false })).toBeInTheDocument();
    expect(within(card).getByText('Band prüfen')).toBeInTheDocument();
  });

  it('409 zeigt „Drucker belegt“', async () => {
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/settings/setup': () =>
          new MockResponse(409, { error: { kind: 'PrinterBusy', message: 'Drucker belegt', hint: '', exit_code: 7, details: null } }),
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const card = document.getElementById('verbindung') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Drucker suchen und testen' }));

    expect(await within(card).findByText('Drucker belegt')).toBeInTheDocument();
  });

  it('„Status abfragen“ ruft die Frischabfrage auf', async () => {
    let called = false;
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/status/refresh': () => {
          called = true;
          return {
            report: { state: { state: 'bereit', transport: 'bt:COM5', last_error: null, leased: false }, status: null, checked_at: null },
            view: { chip: 'Bereit', role: 'success', title: 'Bereit', detail: 'Bereit', tooltip: 'Bereit' },
          };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = document.getElementById('verbindung') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Status abfragen' }));
    await waitFor(() => expect(called).toBe(true));
  });

  it('„Testlabel drucken“ druckt ein Testlabel', async () => {
    let printed: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/labels/print': ({ body }) => {
          printed = body;
          return {
            status: 'ok',
            warnings: [],
            reasons: [],
            history_id: 1,
            consumed_mm: 10,
            results: [],
            printer_status: null,
            error: null,
            queue_id: null,
            job_key: 'k1',
            title: 'Test',
            balance_text: '',
          };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = document.getElementById('verbindung') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Testlabel drucken' }));
    await waitFor(() => expect(printed).toMatchObject({ source: { kind: 'test' } }));
  });
  describe('Druckerverbindung unter „Erweitert“: Speichern meldet Erfolg wie die generischen Karten', () => {
    function settingsWith(restart: boolean): SettingsJson {
      const base = makeSettings();
      return {
        ...base,
        sections: base.sections.map((sec) =>
          sec.id === 'verbindung'
            ? {
                ...sec,
                fields: [
                  ...sec.fields,
                  {
                    key: 'connection.auto_reconnect',
                    label: 'Automatisch neu verbinden',
                    type: 'bool',
                    value: false,
                    default: false,
                    nullable: false,
                    restart,
                    help: '',
                    visibility: 'erweitert',
                  },
                ],
              }
            : sec,
        ),
      } as SettingsJson;
    }

    it.each([
      [true, true],
      [false, false],
    ])('restart=%s: Erfolgsmeldung, Neustart-Hinweis=%s', async (restart, expectRestart) => {
      let patched: unknown = null;
      mockApi(
        baseSettingsRoutes({
          'GET /api/v1/settings': () => settingsWith(restart),
          'PATCH /api/v1/settings': ({ body }) => {
            patched = body;
            return settingsWith(restart);
          },
        }),
      );
      const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen?abschnitt=erweitert-verbindung' });
      const toggle = await screen.findByRole('switch', { name: 'Automatisch neu verbinden' });
      await user.click(toggle);
      const card = document.getElementById('erweitert-verbindung') as HTMLElement;
      await user.click(within(card).getByRole('button', { name: 'Speichern' }));
      await waitFor(() => expect(patched).not.toBeNull());
      expect(await screen.findByText('Druckerverbindung: gespeichert')).toBeInTheDocument();
      if (expectRestart) {
        expect(screen.getByText('Neustart nötig, damit alles wirkt.')).toBeInTheDocument();
      } else {
        expect(screen.queryByText('Neustart nötig, damit alles wirkt.')).not.toBeInTheDocument();
      }
    });
  });

  describe('Statuswerte als zweispaltige Liste', () => {
    const LONG = 'fehler: ' + 'x'.repeat(200);
    const DETAIL = [
      'Verbindung: getrennt',
      'Akku: nicht verfügbar',
      'Deckel: nicht verfügbar',
      'Transport: COM5',
      `Letzter Fehler: ${LONG}`,
    ].join('\n');
    const routes = () =>
      baseSettingsRoutes({
        'GET /api/v1/status': () => ({
          report: { state: { state: 'getrennt', transport: 'COM5', last_error: LONG, leased: false }, status: null, checked_at: null },
          view: { chip: 'Getrennt', role: 'warning', title: 'Getrennt', detail: DETAIL, tooltip: 'Getrennt' },
        }),
      });

    it('zeigt Beschriftung und Wert je Zeile als dt/dd, fehlende Werte gedämpft', async () => {
      mockApi(routes());
      renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
      const card = document.getElementById('verbindung') as HTMLElement;
      const list = await within(card).findByTestId('connection-status-detail');
      expect(list.tagName).toBe('DL');
      expect(list).toHaveAccessibleName('Statuswerte');
      const terms = Array.from(list.querySelectorAll('dt')).map((dt) => dt.textContent);
      const values = Array.from(list.querySelectorAll('dd')).map((dd) => dd.textContent);
      expect(terms).toEqual(['Verbindung', 'Akku', 'Deckel', 'Transport', 'Letzter Fehler']);
      expect(values).toEqual(['getrennt', 'nicht verfügbar', 'nicht verfügbar', 'COM5', LONG]);
      const [, akku, , transport] = Array.from(list.querySelectorAll('dd'));
      expect(akku?.className).not.toBe(transport?.className);
      // Kein Fließtext mehr: der alte Hilfetext mit allen Zeilen hintereinander fehlt.
      expect(within(card).queryByText(/Akku: nicht verfügbar/)).not.toBeInTheDocument();
    });

    it('übersetzt Beschriftungen und „nicht verfügbar“ ins Englische', async () => {
      mockApi(routes());
      renderWithProviders(<EinstellungenPage />, { route: '/einstellungen', language: 'en' });
      const card = document.getElementById('verbindung') as HTMLElement;
      const list = await within(card).findByTestId('connection-status-detail');
      expect(list).toHaveAccessibleName('Status values');
      const terms = Array.from(list.querySelectorAll('dt')).map((dt) => dt.textContent);
      expect(terms).toEqual(['Connection', 'Battery', 'Lid', 'Transport', 'Last error']);
      expect(within(list).getAllByText('not available')).toHaveLength(2);
    });
  });
});
