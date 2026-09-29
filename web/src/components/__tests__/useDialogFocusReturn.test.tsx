import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useDialogFocusReturn } from '../useDialogFocusReturn';

function Probe(props: { removeTrigger?: boolean }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [gone, setGone] = useState(false);
  useDialogFocusReturn(open);
  return (
    <div>
      {gone ? null : (
        <button type="button" onClick={() => setOpen(true)}>
          Öffnen
        </button>
      )}
      {open ? (
        <div role="dialog" aria-label="Probe">
          <input aria-label="Feld" autoFocus />
          <button
            type="button"
            onClick={() => {
              if (props.removeTrigger) setGone(true);
              setOpen(false);
            }}
          >
            Schließen
          </button>
        </div>
      ) : null}
    </div>
  );
}

describe('useDialogFocusReturn', () => {
  it('gibt den Fokus nach dem Schließen an den Auslöser zurück', async () => {
    const user = userEvent.setup();
    render(<Probe />);
    const trigger = screen.getByRole('button', { name: 'Öffnen' });
    await user.click(trigger);
    expect(screen.getByRole('textbox', { name: 'Feld' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Schließen' }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('ignoriert einen Auslöser, der nicht mehr im Dokument steckt', async () => {
    const user = userEvent.setup();
    render(<Probe removeTrigger />);
    await user.click(screen.getByRole('button', { name: 'Öffnen' }));
    await user.click(screen.getByRole('button', { name: 'Schließen' }));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByRole('button', { name: 'Öffnen' })).toBeNull();
    expect(document.activeElement === document.body || document.activeElement === null).toBe(true);
  });
});
