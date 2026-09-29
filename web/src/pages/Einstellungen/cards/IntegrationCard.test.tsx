import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { findDialogByRole, mockApi, renderWithProviders } from '../../../test/utils';
import { baseSettingsRoutes } from '../testFixtures';
import EinstellungenPage from '../index';
import { IntegrationCard } from './IntegrationCard';

/** Karte mit allen drei Einträgen (auf der Seite verteilt auf „Windows-Integration“ und „Erweitert“). */
function AllParts(): JSX.Element {
  return <IntegrationCard id="integration" parts={['autostart', 'context', 'uri']} />;
}

describe('Karte Windows-Integration', () => {
  it('„Vorschau der Änderungen“ sendet dry_run: true und zeigt die Zeilen', async () => {
    let sentBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/integration/install': ({ body }) => {
          sentBody = body;
          return { status: { context: 'installiert', uri: 'nicht installiert', autostart: 'nicht installiert' }, lines: ['HKCU\\...\\shell hinzugefügt'] };
        },
      }),
    );
    const { user } = renderWithProviders(<AllParts />, { route: '/einstellungen' });
    const card = await waitFor(() => document.getElementById('integration') as HTMLElement);

    await user.click(within(card).getByRole('switch', { name: 'Kontextmenü' }));
    await user.click(within(card).getByRole('button', { name: 'Vorschau der Änderungen' }));

    expect(sentBody).toMatchObject({ context: true, dry_run: true });
    expect(await within(card).findByText(/shell hinzugefügt/)).toBeInTheDocument();
  });

  it('Übernehmen fragt nach und sendet ohne dry_run', async () => {
    let sentBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/integration/install': ({ body }) => {
          sentBody = body;
          return { status: { context: 'installiert', uri: 'nicht installiert', autostart: 'nicht installiert' }, lines: [] };
        },
      }),
    );
    const { user } = renderWithProviders(<AllParts />, { route: '/einstellungen' });
    const card = await waitFor(() => document.getElementById('integration') as HTMLElement);

    await user.click(within(card).getByRole('button', { name: 'Übernehmen' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Übernehmen', hidden: true }));

    expect(sentBody).toMatchObject({ dry_run: false });
  });

  it('zeigt Schalter passend zum Ist-Zustand und sendet uninstall beim Ausschalten', async () => {
    let installBody: unknown = null;
    let uninstallBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/integration': () => ({
          status: { context: 'installiert', uri: 'teilweise', autostart: 'nicht installiert' },
          lines: [],
        }),
        'POST /api/v1/integration/install': ({ body }) => {
          installBody = body;
          return { status: { context: 'installiert', uri: 'teilweise', autostart: 'installiert' }, lines: ['Autostart eingerichtet'] };
        },
        'POST /api/v1/integration/uninstall': ({ body }) => {
          uninstallBody = body;
          return { status: { context: 'nicht installiert', uri: 'teilweise', autostart: 'nicht installiert' }, lines: ['Kontextmenü entfernt'] };
        },
      }),
    );
    const { user } = renderWithProviders(<AllParts />, { route: '/einstellungen' });
    const card = await waitFor(() => document.getElementById('integration') as HTMLElement);

    const contextSwitch = await within(card).findByRole('switch', { name: 'Kontextmenü', checked: true });
    await within(card).findByRole('switch', { name: 'URI-Schema tapesmith://', checked: true });
    const autostartSwitch = within(card).getByRole('switch', { name: 'Autostart der Tray-App' });
    expect(autostartSwitch).not.toBeChecked();

    await user.click(contextSwitch);
    await user.click(autostartSwitch);
    await user.click(within(card).getByRole('button', { name: 'Übernehmen' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Übernehmen', hidden: true }));

    expect(installBody).toMatchObject({ context: false, uri: false, autostart: true, dry_run: false });
    expect(uninstallBody).toMatchObject({ context: true, uri: false, autostart: false, dry_run: false });
  });

  it('Seite: Autostart sichtbar, Kontextmenü und URI-Schema unter „Erweitert“; Übernehmen ändert nur die eigenen Einträge', async () => {
    let installBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/integration': () => ({
          status: { context: 'installiert', uri: 'installiert', autostart: 'nicht installiert' },
          lines: [],
        }),
        'POST /api/v1/integration/install': ({ body }) => {
          installBody = body;
          return { status: { context: 'installiert', uri: 'installiert', autostart: 'installiert' }, lines: [] };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = await waitFor(() => {
      const el = document.getElementById('integration');
      if (!el) throw new Error('Karte fehlt');
      return el;
    });
    expect(within(card).queryByRole('switch', { name: 'Kontextmenü' })).not.toBeInTheDocument();
    expect(document.getElementById('integration-erweitert')).toBeNull();
    await user.click(within(card).getByRole('switch', { name: 'Autostart der Tray-App' }));
    await user.click(within(card).getByRole('button', { name: 'Übernehmen' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Übernehmen', hidden: true }));
    await waitFor(() => expect(installBody).toMatchObject({ context: false, uri: false, autostart: true }));
  });

  it('veralteter Eintrag: neutraler Hinweis statt roter Plakette', async () => {
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/integration': () => ({
          status: { context: 'veraltet', uri: 'installiert', autostart: 'installiert' },
          lines: [],
        }),
      }),
    );
    renderWithProviders(<AllParts />, { route: '/einstellungen' });
    expect(await screen.findByText('Eintrag stammt von einer älteren Version, mit Übernehmen aktualisieren.')).toBeInTheDocument();
    expect(screen.queryByText('veraltet')).not.toBeInTheDocument();
    for (const badge of document.querySelectorAll('.fui-Badge')) {
      expect(badge.className).not.toMatch(/danger|severe/);
    }
  });
});
