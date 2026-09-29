import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { findDialogByRole, fixtures, mockApi, MockResponse, renderWithProviders } from '../../test/utils';
import type { LabelSource, PrintOptions, TextSource } from '../../api/types';
import SchnelldruckPage from './index';

function baseRoutes(overrides: Record<string, (req: { body: unknown; query: URLSearchParams }) => unknown> = {}) {
  return {
    'GET /api/v1/labels/fonts': () => ({ fonts: [] }),
    'GET /api/v1/labels/recent-texts': () => ({ items: [] }),
    'POST /api/v1/connection/preconnect': () => ({}),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    ...overrides,
  };
}

async function waitForPreview() {
  await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
}

describe('Schnelldruck', () => {
  it('Tippen fuehrt zu genau einem Render mit den getippten Zeilen, Vorschau erscheint', async () => {
    const api = mockApi(baseRoutes());
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'SSD-1');
    await waitForPreview();
    const renders = api.calls.filter((c) => c.path.startsWith('/api/v1/labels/render'));
    expect(renders).toHaveLength(1);
    expect((renders[0]?.body as { source: LabelSource }).source).toMatchObject({ kind: 'text', lines: ['SSD-1'] });
  });

  it('Schriftgröße in den Optionen: feste Texthöhe geht als text_height_mm an die Vorschau', async () => {
    const api = mockApi(baseRoutes());
    const { user } = renderWithProviders(<SchnelldruckPage />);
    await user.type(screen.getByRole('textbox', { name: 'Labeltext' }), 'SSD-1');
    await waitForPreview();
    await user.click(screen.getByRole('button', { name: 'Mehr Optionen' }));
    const size = screen.getByRole('combobox', { name: 'Schriftgröße' });
    expect(size).toHaveTextContent('Automatisch');
    await user.click(size);
    await user.click(await screen.findByRole('option', { name: '5 mm' }));
    await waitFor(() => {
      const renders = api.calls.filter((c) => c.path.startsWith('/api/v1/labels/render'));
      expect((renders[renders.length - 1]?.body as { source: TextSource }).source.text_height_mm).toBe(5);
    });
  });

  it('Enter bei aktueller Vorschau druckt 1 Label, Strg+Enter mit 3 Kopien druckt 3', async () => {
    const api = mockApi(
      baseRoutes({
        'POST /api/v1/labels/print': ({ body }) => {
          const opts = (body as { options: { copies: number } }).options;
          return fixtures.outcomeJson({ status: 'ok', title: 'Test', results: [{ rows: 1, rows_sent: 1, waited_s: 0, status: opts.copies === 3 ? '3' : '1' }] });
        },
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'SSD-1');
    await waitForPreview();

    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    let printCall = api.calls.find((c) => c.path === '/api/v1/labels/print');
    expect((printCall?.body as { options: PrintOptions }).options.copies).toBe(1);

    await user.click(screen.getByRole('button', { name: 'Mehr Optionen' }));
    const spin = screen.getByRole('spinbutton', { name: 'Kopien' });
    await user.click(spin);
    await user.keyboard('{ArrowUp}{ArrowUp}');
    // Kopien beeinflusst die Vorschau (Plan): warten, bis die dadurch neu ausgelöste Anfrage durch ist,
    // sonst ist die Vorschau aus Sicht des Gates noch veraltet.
    await waitFor(() => expect(api.calls.filter((c) => c.path.startsWith('/api/v1/labels/render'))).toHaveLength(2));
    // Entprellung (min. 1 s zwischen zwei Drucken): über die reale Zeit hinweg warten.
    await new Promise((resolve) => setTimeout(resolve, 1100));
    await user.click(textarea);
    await user.keyboard('{Control>}{Enter}{/Control}');

    await waitFor(() => expect(api.calls.filter((c) => c.path === '/api/v1/labels/print')).toHaveLength(2));
    printCall = api.calls.filter((c) => c.path === '/api/v1/labels/print')[1];
    expect((printCall?.body as { options: PrintOptions }).options.copies).toBe(3);
  });

  it('Enter waehrend die Vorschau noch berechnet wird: kein Druck, Meldung erscheint', async () => {
    const resolvers: ((v: unknown) => void)[] = [];
    const api = mockApi(
      baseRoutes({
        'POST /api/v1/labels/render': () => new Promise((resolve) => resolvers.push(() => resolve(fixtures.renderJson()))),
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'X');
    await user.keyboard('{Enter}');
    expect(await screen.findByText(/Vorschau wird noch berechnet/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);
    resolvers.forEach((r) => r(undefined));
  });

  it('Einfuegen von "a\\nb": erstes Enter druckt nicht, zweites Enter druckt', async () => {
    const api = mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'a · b' }) }));
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' }) as HTMLTextAreaElement;
    await user.click(textarea);
    await user.paste('a\nb');
    expect(textarea.value).toBe('a\nb');
    expect(await screen.findByText(/Mehrzeiliger Text wurde eingefügt/)).toBeInTheDocument();

    await waitForPreview();
    await user.keyboard('{Enter}');
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);

    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
  });

  it('Render mit ok:false und Fix: "Beheben" uebernimmt die Fix-Quelle', async () => {
    const fixSource: TextSource = { kind: 'text', lines: ['SSD-1 korrigiert'] };
    let renderCount = 0;
    const api = mockApi(
      baseRoutes({
        'POST /api/v1/labels/render': () => {
          renderCount += 1;
          if (renderCount === 1) {
            return fixtures.renderJson({ ok: false, preview: null, errors: ['Zu lang'], fixes: [{ id: 'f1', label: 'Kürzen', source: fixSource }] });
          }
          return fixtures.renderJson({ title: 'SSD-1 korrigiert' });
        },
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' }) as HTMLTextAreaElement;
    await user.type(textarea, 'X');
    const fixButton = await screen.findByRole('button', { name: 'Beheben: Kürzen' });
    await user.click(fixButton);
    await waitFor(() => expect(textarea.value).toBe('SSD-1 korrigiert'));
    await waitFor(() => expect(api.calls.filter((c) => c.path === '/api/v1/labels/render')).toHaveLength(2));
    const last = api.calls.filter((c) => c.path === '/api/v1/labels/render').at(-1);
    expect((last?.body as { source: LabelSource }).source).toMatchObject({ kind: 'text', lines: ['SSD-1 korrigiert'] });
  });

  it('bestaetigung_noetig zeigt den Dialog, "Trotzdem drucken" sendet confirmed:true', async () => {
    const api = mockApi(
      baseRoutes({
        'POST /api/v1/labels/print': ({ body }) => {
          const confirmed = (body as { options: { confirmed: boolean } }).options.confirmed;
          return confirmed
            ? fixtures.outcomeJson({ status: 'ok', title: 'X' })
            : fixtures.outcomeJson({ status: 'bestätigung_nötig', reasons: ['Band fast leer'] });
        },
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'X');
    await waitForPreview();
    await user.keyboard('{Enter}');
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Band fast leer')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Trotzdem drucken', hidden: true }));
    await waitFor(() => expect(api.calls.filter((c) => c.path === '/api/v1/labels/print')).toHaveLength(2));
    const second = api.calls.filter((c) => c.path === '/api/v1/labels/print')[1];
    expect((second?.body as { options: { confirmed: boolean } }).options.confirmed).toBe(true);
  });

  it('Chip der letzten Texte druckt, Alt+Klick fuellt nur', async () => {
    const api = mockApi(
      baseRoutes({
        'GET /api/v1/labels/recent-texts': () => ({ items: [['Letzter Text']] }),
        'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'Letzter Text' }),
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const chip = await screen.findByRole('button', { name: 'Letzten Text übernehmen: Letzter Text' });

    await user.keyboard('{Alt>}');
    await user.click(chip);
    await user.keyboard('{/Alt}');
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' }) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Letzter Text');

    await user.click(chip);
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const printCall = api.calls.find((c) => c.path === '/api/v1/labels/print');
    expect((printCall?.body as { source: LabelSource }).source).toMatchObject({ kind: 'text', lines: ['Letzter Text'] });
  });

  it('?text= fuellt zwei Zeilen, ohne zu drucken', async () => {
    const api = mockApi(baseRoutes());
    renderWithProviders(<SchnelldruckPage />, { route: '/schnelldruck?text=a%0Ab' });
    const textarea = (await screen.findByRole('textbox', { name: 'Labeltext' })) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toBe('a\nb'));
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);
  });

  it('Erster Tastendruck ruft preconnect genau einmal auf', async () => {
    const api = mockApi(baseRoutes());
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'abc');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/connection/preconnect')).toBe(true));
    expect(api.calls.filter((c) => c.path === '/api/v1/connection/preconnect')).toHaveLength(1);
  });

  it('QR ohne Decoder zeigt "nicht rückgelesen" statt fehlgeschlagen', async () => {
    mockApi(
      baseRoutes({
        'POST /api/v1/labels/render': () =>
          fixtures.renderJson({
            qr: { version: 3, error: 'm', module_dots: 4, decodes: false, checked: false, warnings: [], text: 'QR' },
          }),
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'SSD-1');
    await user.type(screen.getByRole('textbox', { name: 'QR-Inhalt (optional)' }), 'HTTP://L.LAN/D7');
    expect(await screen.findByText(/nicht rückgelesen/)).toBeInTheDocument();
    expect(screen.queryByText(/fehlgeschlagen/)).toBeNull();
  });

  describe('Export', () => {
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;

    afterEach(() => {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    });

    it('Export PNG ruft den Export-Endpunkt mit format png auf', async () => {
      URL.createObjectURL = vi.fn(() => 'blob:mock');
      URL.revokeObjectURL = vi.fn();
      // Download-Link nicht wirklich anklicken (jsdom kennt keine Navigation)
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
      onTestFinished(() => clickSpy.mockRestore());
      const api = mockApi(
        baseRoutes({
          'POST /api/v1/labels/export': () => new MockResponse(200, 'PNGDATA', { 'Content-Type': 'image/png' }),
        }),
      );
      const { user } = renderWithProviders(<SchnelldruckPage />);
      const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
      await user.type(textarea, 'X');
      await waitForPreview();
      await user.click(screen.getByRole('button', { name: 'Exportieren' }));
      await user.click(await screen.findByRole('menuitem', { name: 'PNG' }));
      await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/export')).toBe(true));
      const call = api.calls.find((c) => c.path === '/api/v1/labels/export');
      expect((call?.body as { format: string }).format).toBe('png');
      await waitFor(() => expect(clickSpy).toHaveBeenCalled());
    });
  });
});
