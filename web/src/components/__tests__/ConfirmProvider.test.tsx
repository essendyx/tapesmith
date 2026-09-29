/** Bestätigungsdialog: Fokus auf „Abbrechen“ und beim Schließen zurück zum Auslöser. */
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { Button } from '@fluentui/react-components';
import { findDialog, mockApi, renderWithProviders } from '../../test/utils';
import { useConfirm } from '../ConfirmProvider';

function Trigger(): JSX.Element {
  const confirm = useConfirm();
  const [result, setResult] = useState('offen');
  return (
    <div>
      <Button onClick={() => void confirm({ title: 'Wirklich löschen?', confirmText: 'Löschen' }).then((ok) => setResult(ok ? 'ja' : 'nein'))}>
        Eintrag löschen
      </Button>
      <output>{result}</output>
    </div>
  );
}

describe('ConfirmProvider', () => {
  for (const [label, name] of [
    ['Abbrechen', 'nein'],
    ['Löschen', 'ja'],
  ] as const) {
    it(`gibt den Fokus nach „${label}“ an den Auslöser zurück`, async () => {
      mockApi({}, { quiet: true });
      const { user } = renderWithProviders(<Trigger />);
      const trigger = screen.getByRole('button', { name: 'Eintrag löschen' });
      await user.click(trigger);
      const dialog = await findDialog('Wirklich löschen?');
      const cancel = within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true });
      await waitFor(() => expect(cancel).toHaveFocus());
      await user.click(within(dialog).getByRole('button', { name: label, hidden: true }));
      expect(await screen.findByText(name)).toBeInTheDocument();
      await waitFor(() => expect(trigger).toHaveFocus());
    });
  }

  it('Escape bricht ab und gibt den Fokus zurück', async () => {
    mockApi({}, { quiet: true });
    const { user } = renderWithProviders(<Trigger />);
    const trigger = screen.getByRole('button', { name: 'Eintrag löschen' });
    trigger.focus();
    await user.keyboard('{Enter}');
    await findDialog('Wirklich löschen?');
    await user.keyboard('{Escape}');
    expect(await screen.findByText('nein')).toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
