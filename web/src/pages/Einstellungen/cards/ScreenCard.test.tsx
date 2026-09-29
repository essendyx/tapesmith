import { describe, expect, it } from 'vitest';
import { within } from '@testing-library/react';
import { findDialog, mockApi, renderWithProviders } from '../../../test/utils';
import { baseSettingsRoutes, makeSettings } from '../testFixtures';
import EinstellungenPage from '../index';

describe('Karte Bildschirm', () => {
  it('Übernehmen bei Kartenbreite 342,4 px sendet gui.screen_px_per_mm: 4', async () => {
    let sentChanges: Record<string, unknown> | null = null;
    mockApi(
      baseSettingsRoutes({
        'PATCH /api/v1/settings': ({ body }) => {
          sentChanges = (body as { changes: Record<string, unknown> }).changes;
          return makeSettings();
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const card = document.getElementById('bildschirm') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Bildschirm kalibrieren…' }));

    const dialog = await findDialog('Bildschirm kalibrieren');
    const widthInput = within(dialog).getByLabelText('Kartenbreite in Pixel');
    await user.clear(widthInput);
    await user.type(widthInput, '342.4');
    await user.click(within(dialog).getByRole('button', { name: 'Übernehmen' }));

    expect(sentChanges).toEqual({ 'gui.screen_px_per_mm': 4 });
  });
});
