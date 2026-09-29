/** Tastenkürzel-Übersicht: Öffnen mit ? und F1, Suche, Esc, Fokus zurück, Englisch, axe. */
import { describe, expect, it } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Button, Input } from '@fluentui/react-components';
import { expectNoA11yViolations } from '../../test/a11y';
import { anyDialogInDom, findDialog, mockApi, renderWithProviders } from '../../test/utils';
import { useShortcut } from '../../commands/shortcuts';

function Harness(): JSX.Element {
  useShortcut('Alt+N', () => undefined, { description: 'Neue Notiz anlegen' });
  return (
    <>
      <Button>Auslöser</Button>
      <Input aria-label="Eingabe" />
    </>
  );
}

function press(target: Element, init: KeyboardEventInit) {
  act(() => {
    fireEvent.keyDown(target, init);
  });
}

function renderHarness(language: 'de' | 'en' = 'de') {
  mockApi({}, { quiet: true });
  return renderWithProviders(<Harness />, { language });
}

describe('Tastenkürzel-Übersicht', () => {
  it('? (mit Umschalt) öffnet, Esc schließt und gibt den Fokus an den Auslöser zurück', async () => {
    const { user } = renderHarness();
    const trigger = screen.getByRole('button', { name: 'Auslöser' });
    trigger.focus();
    press(trigger, { key: '?', code: 'Minus', shiftKey: true });
    const dialog = await findDialog('Tastenkürzel');
    const search = within(dialog).getByRole('searchbox', { name: 'Kürzel suchen', hidden: true });
    await waitFor(() => expect(search).toHaveFocus());
    await user.keyboard('{Escape}');
    await waitFor(() => expect(anyDialogInDom()).toBe(false));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('F1 öffnet ebenfalls', async () => {
    renderHarness();
    press(document.body, { key: 'F1', code: 'F1' });
    expect(await findDialog('Tastenkürzel')).toBeInTheDocument();
  });

  it('in einem Eingabefeld öffnet ? nicht', async () => {
    renderHarness();
    const input = screen.getByRole('textbox', { name: 'Eingabe' });
    input.focus();
    press(input, { key: '?', shiftKey: true });
    await new Promise((r) => setTimeout(r, 50));
    expect(anyDialogInDom()).toBe(false);
  });

  it('zeigt Gruppen als Tabellen, registrierte Kürzel und findet mit „tab“ die Editor-Tab-Kürzel', async () => {
    const { user } = renderHarness();
    press(document.body, { key: 'F1' });
    const dialog = await findDialog('Tastenkürzel');
    expect(within(dialog).getByRole('table', { name: 'Überall', hidden: true })).toHaveTextContent('Strg+K');
    expect(within(dialog).getByRole('table', { name: 'Diese Seite', hidden: true })).toHaveTextContent('Neue Notiz anlegen');
    expect(within(dialog).getByRole('table', { name: 'Befehle', hidden: true })).toHaveTextContent('Gehe zu Editor');
    await user.type(within(dialog).getByRole('searchbox', { hidden: true }), 'tab');
    const tabs = within(dialog).getByRole('table', { name: 'Editor-Tabs', hidden: true });
    for (const text of ['Neuer Tab', 'Tab schließen', 'Nächster Tab', 'Voriger Tab', 'Strg+Alt+T', 'Strg+Bild ab']) {
      expect(tabs).toHaveTextContent(text);
    }
    expect(within(dialog).queryByRole('table', { name: 'Überall', hidden: true })).toBeNull();
  });

  it('Englisch: „Ctrl+K“ und englische Gruppen', async () => {
    renderHarness('en');
    press(document.body, { key: 'F1' });
    const dialog = await findDialog('Keyboard shortcuts');
    const global = within(dialog).getByRole('table', { name: 'Everywhere', hidden: true });
    expect(global).toHaveTextContent('Ctrl+K');
    expect(global).toHaveTextContent('Open command palette');
    expect(global).not.toHaveTextContent('Strg');
  });

  it('Kopfzeilen-Knopf öffnet die Übersicht', async () => {
    mockApi({}, { quiet: true });
    const { user } = renderWithProviders(<></>, { withShell: true, route: '/schnelldruck' });
    await user.click(await screen.findByRole('button', { name: 'Tastenkürzel' }));
    expect(await findDialog('Tastenkürzel')).toBeInTheDocument();
  });

  for (const language of ['de', 'en'] as const) {
    it(`axe ohne Befund (${language})`, async () => {
      renderHarness(language);
      press(document.body, { key: 'F1' });
      await findDialog(language === 'de' ? 'Tastenkürzel' : 'Keyboard shortcuts');
      await expectNoA11yViolations(document.body);
    });
  }
});
