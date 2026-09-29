import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { Button } from '@fluentui/react-components';
import { findDialogByRole, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import { usePrint } from '../usePrint';
import type { LabelSource, OutcomeJson } from '../../api/types';

const SOURCE: LabelSource = { kind: 'text', lines: ['Hallo'] };

function PrintButton(props: { onResult?: (o: OutcomeJson | null) => void }) {
  const print = usePrint();
  return (
    <>
      <Button onClick={() => void print.run(SOURCE, { copies: 2 }).then((o) => props.onResult?.(o))}>Drucken</Button>
      <output data-testid="busy">{print.busy ? 'ja' : 'nein'}</output>
    </>
  );
}

describe('usePrintFlow', () => {
  it('bestätigung_nötig zeigt Dialog mit Gründen, „Trotzdem drucken“ sendet mit confirmed', async () => {
    const api = mockApi({
      'POST /api/v1/labels/print': ({ body }) => {
        const opts = (body as { options: { confirmed: boolean } }).options;
        return opts.confirmed
          ? fixtures.outcomeJson({ status: 'ok', title: 'Hallo' })
          : fixtures.outcomeJson({ status: 'bestätigung_nötig', reasons: ['Vorschau veraltet', 'Band passt nicht'] });
      },
    });
    const { user } = renderWithProviders(<PrintButton />);
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Wirklich drucken?')).toBeInTheDocument();
    expect(within(dialog).getByText('Vorschau veraltet')).toBeInTheDocument();
    expect(within(dialog).getByText('Band passt nicht')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Trotzdem drucken', hidden: true }));
    await screen.findByText('Gedruckt: Hallo');
    const prints = api.calls.filter((c) => c.path === '/api/v1/labels/print');
    expect(prints).toHaveLength(2);
    const first = (prints[0]?.body as { options: { confirmed: boolean; job_key: string; copies: number } }).options;
    const second = (prints[1]?.body as { options: { confirmed: boolean; job_key: string } }).options;
    expect(first.confirmed).toBe(false);
    expect(first.copies).toBe(2);
    expect(second.confirmed).toBe(true);
    expect(second.job_key).not.toBe(first.job_key);
  });

  it('„Abbrechen“ im Dialog sendet nichts mehr, Fokus steht auf „Abbrechen“', async () => {
    const api = mockApi({
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'bestätigung_nötig', reasons: ['Leer'] }),
    });
    const { user } = renderWithProviders(<PrintButton />);
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    const dialog = await findDialogByRole('alertdialog');
    const cancel = within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true });
    await waitFor(() => expect(cancel).toHaveFocus());
    await user.click(cancel);
    await waitFor(() => expect(screen.getByTestId('busy')).toHaveTextContent('nein'));
    expect(api.calls.filter((c) => c.path === '/api/v1/labels/print')).toHaveLength(1);
  });

  it('ok zeigt Erfolgsmeldung, zweiter Aufruf während busy wird ignoriert', async () => {
    let release: (() => void) | undefined;
    const api = mockApi({
      'POST /api/v1/labels/print': () =>
        new Promise((resolve) => {
          release = () => resolve(fixtures.outcomeJson({ status: 'ok', title: 'Hallo' }));
        }),
    });
    const { user } = renderWithProviders(<PrintButton />);
    const button = screen.getByRole('button', { name: 'Drucken' });
    await user.click(button);
    await waitFor(() => expect(screen.getByTestId('busy')).toHaveTextContent('ja'));
    await user.click(button);
    release?.();
    expect(await screen.findByText('Gedruckt: Hallo')).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === '/api/v1/labels/print')).toHaveLength(1);
  });

  it('abgelehnt und ApiError ergeben Fehlermeldungen mit Hinweis', async () => {
    const { MockResponse } = await import('../../test/utils');
    let n = 0;
    mockApi({
      'POST /api/v1/labels/print': () => {
        n += 1;
        if (n === 1) return fixtures.outcomeJson({ status: 'abgelehnt', reasons: ['Band leer'] });
        return new MockResponse(409, { error: { kind: 'PrinterBusy', message: 'Drucker belegt', hint: 'Später erneut', exit_code: 7, details: null } });
      },
    });
    const { user } = renderWithProviders(<PrintButton />);
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Nicht gedruckt')).toBeInTheDocument();
    expect(screen.getByText('Band leer')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('busy')).toHaveTextContent('nein'));
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Drucker belegt')).toBeInTheDocument();
    expect(screen.getByText('Später erneut')).toBeInTheDocument();
  });

  it('wartet ergibt Warnung mit erster Warnung', async () => {
    mockApi({
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'wartet', title: 'Hallo', warnings: ['Drucker offline, Auftrag wartet'] }),
    });
    const { user } = renderWithProviders(<PrintButton />);
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Drucker offline, Auftrag wartet')).toBeInTheDocument();
  });
});
