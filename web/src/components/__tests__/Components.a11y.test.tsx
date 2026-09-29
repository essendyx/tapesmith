/** Gemeinsame Komponenten in typischem Zustand: axe ohne Befund in de und en. */
import { useEffect, useState } from 'react';
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Button } from '@fluentui/react-components';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialogByRole, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import { DEFAULT_PRINT_OPTIONS, type PrintOptions } from '../../api/types';
import { useConfirm } from '../ConfirmProvider';
import { useNotify } from '../NotifyProvider';
import { PlausiHint } from '../PlausiHint';
import { PrintOptionsBar } from '../PrintOptionsBar';
import { TapePreview } from '../TapePreview';
import { WarningList } from '../WarningList';

const LANGS = ['de', 'en'] as const;

function Options() {
  const [value, setValue] = useState<PrintOptions>({ ...DEFAULT_PRINT_OPTIONS, chain: true });
  return <PrintOptionsBar value={value} onChange={setValue} />;
}

function ConfirmOpen() {
  const confirm = useConfirm();
  useEffect(() => {
    void confirm({ title: 'Löschen?', message: 'Wirklich?', reasons: ['Grund A'], confirmText: 'Löschen', danger: true });
  }, [confirm]);
  return null;
}

function ToastShown() {
  const notify = useNotify();
  return <Button onClick={() => notify({ intent: 'error', title: 'Drucker aus', body: 'Kein Kontakt', hint: 'Einschalten' })}>Melden</Button>;
}

describe('Komponenten a11y', () => {
  for (const language of LANGS) {
    it(`Vorschau, Warnliste mit drei Stufen, Druckoptionen, Plausi-Hinweis (${language})`, async () => {
      mockApi({}, { quiet: true });
      const render = fixtures.renderJson({ errors: ['Fehler A'], warnings: ['Warnung B'], notes: ['Hinweis C'] });
      const { container } = renderWithProviders(
        <main>
          <TapePreview render={render} onZoomChange={() => undefined} />
          <WarningList errors={['E']} warnings={['W']} notes={['N']} />
          <Options />
          <PlausiHint
            findings={[
              { level: 'konflikt', field: 'sn', code: 'x', message: 'Konflikt' },
              { level: 'warnung', field: 'ip', code: 'y', message: 'Warnung' },
              { level: 'info', field: 'sn', code: 'z', message: 'Info' },
            ]}
          />
        </main>,
        { language },
      );
      expect(screen.getAllByRole('list').length).toBeGreaterThan(0);
      await expectNoA11yViolations(container);
    });

    it(`Rückfrage offen, Fokus auf der sicheren Aktion (${language})`, async () => {
      mockApi({}, { quiet: true });
      renderWithProviders(<ConfirmOpen />, { language });
      const dialog = await findDialogByRole('alertdialog');
      const cancel = await screen.findByRole('button', { name: language === 'de' ? 'Abbrechen' : 'Cancel' });
      await expect.poll(() => document.activeElement).toBe(cancel);
      expect(dialog).toBeInTheDocument();
      await expectNoA11yViolations(document.body);
    });

    it(`Toast sichtbar (${language})`, async () => {
      mockApi({}, { quiet: true });
      const { user } = renderWithProviders(<ToastShown />, { language });
      await user.click(screen.getByRole('button', { name: 'Melden' }));
      expect(await screen.findByText('Drucker aus')).toBeInTheDocument();
      await expectNoA11yViolations(document.body);
    });
  }

  it('Englisch: Druckoptionen und Warnstufen übersetzt', () => {
    mockApi({}, { quiet: true });
    renderWithProviders(
      <>
        <Options />
        <WarningList errors={['E']} warnings={['W']} notes={['N']} />
      </>,
      { language: 'en' },
    );
    expect(screen.getByRole('group', { name: 'Print options' })).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: 'Copies' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'As a chain' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Cut pause' })).toHaveTextContent('Default');
    expect(screen.getByText('Error:', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Warning:', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Note:', { exact: false })).toBeInTheDocument();
  });
});
