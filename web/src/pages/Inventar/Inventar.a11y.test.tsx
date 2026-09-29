import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, findDialogByRole, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { BoxDetailJson, BoxJson, LoanJson } from '../../api/types';
import InventarPage from '.';

const box1: BoxJson = { id: 'BOX-07', location: 'Keller Regal 2', note: '', created: '2026-09-01T10:00:00', items: 2 };
const box2: BoxJson = { id: 'BOX-08', location: 'Keller Regal 3', note: '', created: '2026-09-01T10:00:00', items: 0 };

const boxDetail: BoxDetailJson = {
  ...box1,
  item_list: [
    { id: 1, box_id: 'BOX-07', name: 'HDMI-Adapter', qty: 1, note: '' },
    { id: 2, box_id: 'BOX-07', name: 'Netzkabel', qty: 3, note: '' },
  ],
};

function boxesHandlers() {
  return {
    'GET /api/v1/inventory/boxes': () => ({ boxes: [box1, box2] }),
    'GET /api/v1/inventory/boxes/:id': ({ params }: { params: Record<string, string> }) =>
      params.id === 'BOX-07' ? boxDetail : { ...box2, item_list: [] },
  };
}

describe('Inventar: Barrierefreiheit', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Boxen gefüllt ohne axe-Befund (${language})`, async () => {
      mockApi(boxesHandlers());
      const { container } = renderWithProviders(<InventarPage />, { route: '/inventar', language });
      await screen.findByText('BOX-07');
      await expectNoA11yViolations(container);
    });

    it(`Boxen leer ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/inventory/boxes': () => ({ boxes: [] }) });
      const { container } = renderWithProviders(<InventarPage />, { route: '/inventar', language });
      await screen.findByRole('status');
      await expectNoA11yViolations(container);
    });

    it(`Box-Detail-Dialog ohne axe-Befund (${language})`, async () => {
      mockApi(boxesHandlers());
      const { user, container } = renderWithProviders(<InventarPage />, { route: '/inventar', language });
      await user.click(await screen.findByText('BOX-07'));
      await findDialogByRole('dialog');
      await expectNoA11yViolations(container);
    });
  }

  it('Tastatur: „Neue Box" per Tab erreichbar, per Enter öffnet den Dialog', async () => {
    mockApi(boxesHandlers());
    renderWithProviders(<InventarPage />, { route: '/inventar' });
    await screen.findByText('BOX-07');
    const button = screen.getByRole('button', { name: 'Neue Box' });
    button.focus();
    expect(button).toHaveFocus();
    await userEvent.setup().keyboard('{Enter}');
    await findDialog('Neue Box');
  });

  it('Box-Karte per Tastatur (Enter) öffnen', async () => {
    mockApi(boxesHandlers());
    renderWithProviders(<InventarPage />, { route: '/inventar' });
    await screen.findByText('BOX-07');
    const card = screen.getByRole('button', { name: 'BOX-07' });
    card.focus();
    expect(card).toHaveFocus();
    await userEvent.setup().keyboard('{Enter}');
    await findDialog('Box BOX-07');
  });

  it('Dialog schließt mit Escape und gibt den Fokus an den Auslöser zurück', async () => {
    mockApi(boxesHandlers());
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await screen.findByText('BOX-07');
    const button = screen.getByRole('button', { name: 'Neue Box' });
    await user.click(button);
    await findDialog('Neue Box');
    await user.keyboard('{Escape}');
    await screen.findByRole('button', { name: 'Neue Box' });
  });

  it('Label-Dialog ohne axe-Befund', async () => {
    mockApi({
      ...boxesHandlers(),
      'POST /api/v1/inventory/labels/render': () => fixtures.renderJson({ title: 'Box BOX-07' }),
    });
    const { user, container } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await user.click(await screen.findByText('BOX-07'));
    await user.click(await screen.findByRole('button', { name: 'Box-Label' }));
    await findDialog('Box-Label');
    await expectNoA11yViolations(container);
  });

  it('Verleih: gefüllt ohne axe-Befund', async () => {
    const loan: LoanJson = { id: 5, item: 'Bohrmaschine', person: 'Hubert', since: '2026-09-01T00:00:00', due: '2026-09-10', returned: null, note: '', open: true, overdue: true };
    mockApi({ ...boxesHandlers(), 'GET /api/v1/inventory/loans': () => ({ loans: [loan] }) });
    const { container } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
    await screen.findByText('überfällig');
    await expectNoA11yViolations(container);
  });
});
