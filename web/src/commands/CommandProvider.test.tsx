/** Befehle für Sprache, Farbschema und Tastenkürzel. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import type { AppInfo } from '../api/types';
import { i18n } from '../i18n';
import { findDialog, fixtures, LocationProbe, mockApi, renderWithProviders } from '../test/utils';

function settingsApi(language: AppInfo['language'] = 'de') {
  const state: { language: AppInfo['language']; theme: AppInfo['theme'] } = { language, theme: 'system' };
  const api = mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
      'GET /api/v1/app': () => ({ ...fixtures.appInfo, language: state.language, theme: state.theme }),
      'PATCH /api/v1/settings': ({ body }) => {
        const changes = (body as { changes: Record<string, string> }).changes;
        if (changes['app.language']) state.language = changes['app.language'] as AppInfo['language'];
        if (changes['app.theme']) state.theme = changes['app.theme'] as AppInfo['theme'];
        return { sections: [], config_path: 'config.json' };
      },
    },
    { quiet: true },
  );
  return { api, state };
}

async function runCommand(user: ReturnType<typeof renderWithProviders>['user'], query: string, title: string) {
  await user.keyboard('{Control>}k{/Control}');
  const input = await screen.findByRole('combobox', { name: 'Befehl suchen' });
  await user.type(input, query);
  await waitFor(() =>
    expect(within(screen.getByRole('listbox', { name: 'Befehle' })).getAllByRole('option')[0]).toHaveTextContent(title),
  );
  await user.keyboard('{Enter}');
}

describe('Befehle Sprache und Farbschema', () => {
  it('„Sprache: English“ sendet PATCH app.language, lädt AppInfo neu, Seitenleiste wird englisch', async () => {
    const { api } = settingsApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    const appCalls = () => api.calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/app').length;
    const before = appCalls();
    await runCommand(user, 'english', 'Sprache: English');
    await waitFor(() =>
      expect(api.calls).toContainEqual({ method: 'PATCH', path: '/api/v1/settings', body: { changes: { 'app.language': 'en' } } }),
    );
    await waitFor(() => expect(appCalls()).toBeGreaterThan(before));
    expect(await screen.findByRole('navigation', { name: 'Pages' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Quick print' })).toBeInTheDocument();
    expect(await screen.findByText('Language changed')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
    expect(i18n.language).toBe('en');
  });

  it('„Farbschema: Dunkel“ sendet PATCH app.theme', async () => {
    const { api, state } = settingsApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await runCommand(user, 'dunkel', 'Farbschema: Dunkel');
    await waitFor(() =>
      expect(api.calls).toContainEqual({ method: 'PATCH', path: '/api/v1/settings', body: { changes: { 'app.theme': 'dunkel' } } }),
    );
    expect(state.theme).toBe('dunkel');
    expect(await screen.findByText('Farbschema umgestellt')).toBeInTheDocument();
  });

  it('„Tastenkürzel anzeigen“ öffnet die Übersicht', async () => {
    settingsApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await runCommand(user, 'tastenk', 'Tastenkürzel anzeigen');
    expect(await findDialog('Tastenkürzel')).toBeInTheDocument();
  });

  it('Gruppen der Seiten („Drucken“) und eingebaute Gruppen erscheinen zusammen und übersetzt', async () => {
    settingsApi('en');
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik', language: 'en' });
    await screen.findByRole('navigation', { name: 'Pages' });
    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Search commands' });
    await user.type(input, 'reprint');
    const list = screen.getByRole('listbox', { name: 'Commands' });
    expect(within(list).getByRole('group', { name: 'Print' })).toHaveTextContent('Reprint last label');
  });
});
