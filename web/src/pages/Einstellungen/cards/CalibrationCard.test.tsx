import { describe, expect, it } from 'vitest';
import { waitFor, within } from '@testing-library/react';
import { findDialogByRole, mockApi, renderWithProviders } from '../../../test/utils';
import { baseSettingsRoutes } from '../testFixtures';
import EinstellungenPage from '../index';

describe('Karte Kalibrierung', () => {
  it('„Lineal drucken“ sendet labels/print mit calibration/ruler', async () => {
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
            consumed_mm: 100,
            results: [],
            printer_status: null,
            error: null,
            queue_id: null,
            job_key: 'k1',
            title: 'Lineal',
            balance_text: '',
          };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = document.getElementById('kalibrierung') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Lineal drucken (100 mm)' }));

    const body = printed as { source: { kind: string; which: string } };
    expect(body.source).toEqual({ kind: 'calibration', which: 'ruler' });
  });

  it('Übernehmen mit 98,5 sendet measured_mm: 98.5', async () => {
    let sentBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'POST /api/v1/calibration/length': ({ body }) => {
          sentBody = body;
          return { length_factor: 1.02, leader_mm: 5, trailer_mm: 5, content_offset: 8, content_dots: 80, verified: [], path: '' };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = document.getElementById('kalibrierung') as HTMLElement;

    const input = within(card).getByLabelText('Gemessene Länge (mm)');
    await user.clear(input);
    await user.type(input, '98,5');
    await user.click(within(card).getByRole('button', { name: 'Übernehmen' }));

    expect(sentBody).toMatchObject({ measured_mm: 98.5 });
  });

  it('„Längenfaktor zurücksetzen“ fragt nach und sendet DELETE calibration/length', async () => {
    let deleted = 0;
    const cal = { leader_mm: 5, trailer_mm: 5, content_offset: 8, content_dots: 80, verified: [], path: '' };
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/calibration': () => ({ ...cal, length_factor: 1.0204 }),
        'DELETE /api/v1/calibration/length': () => {
          deleted += 1;
          return { ...cal, length_factor: 1 };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = await waitFor(() => {
      const el = document.getElementById('kalibrierung');
      if (!el) throw new Error('Karte fehlt');
      return el;
    });
    const reset = await within(card).findByRole('button', { name: 'Längenfaktor zurücksetzen' });
    await waitFor(() => expect(reset).toBeEnabled());
    await user.click(reset);
    const dialog = await findDialogByRole('alertdialog');
    await user.click(await within(dialog).findByRole('button', { name: 'Längenfaktor zurücksetzen', hidden: true }));
    await waitFor(() => expect(deleted).toBe(1));
    await waitFor(() => expect(within(card).getByRole('button', { name: 'Längenfaktor zurücksetzen' })).toBeDisabled());
  });
});
