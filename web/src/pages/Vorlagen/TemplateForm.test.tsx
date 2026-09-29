import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { FieldJson } from '../../api/types';
import { TemplateForm } from './TemplateForm';

afterEach(() => {
  restoreAllMocks();
});

function field(o: Partial<FieldJson> = {}): FieldJson {
  return { id: 'sn', label: 'Seriennummer', type: 'input', default: '', required: false, secret: false, choices: [], max_len: null, multiline: false, ...o };
}

const SIZE = field({
  id: 'schriftgroesse',
  label: 'Schriftgröße',
  default: 'auto',
  choices: ['auto', 'auto-feld', '2', '2.5', '9'],
  role: 'text_size',
});

describe('TemplateForm', () => {
  it('Auswahl zeigt Beschriftungen (choice_labels), liefert aber den Wert', async () => {
    const onChange = vi.fn();
    const routing = field({
      id: 'verlauf',
      label: 'Routing',
      choices: ['haengt', 'steht_ab'],
      choice_labels: { haengt: 'hangs on a horizontal cable', steht_ab: 'sticks out from a vertical cable' },
    });
    const { user } = renderWithProviders(
      <TemplateForm fields={[routing]} values={{ verlauf: 'haengt' }} computed={null} onChange={onChange} />,
      { language: 'en' },
    );
    const combo = screen.getByRole('combobox', { name: 'Routing' });
    expect(combo).toHaveValue('hangs on a horizontal cable');
    await user.click(combo);
    await user.click(await screen.findByRole('option', { name: 'sticks out from a vertical cable' }));
    expect(onChange).toHaveBeenCalledWith('verlauf', 'steht_ab');
  });


  it('Pflichtfeld zeigt genau einen Stern', () => {
    renderWithProviders(<TemplateForm fields={[field({ required: true })]} values={{}} computed={null} onChange={() => {}} />);
    const label = screen.getByText(/Seriennummer/).closest('label');
    expect(label?.textContent ?? '').not.toMatch(/\*\s*\*/);
    expect((label?.textContent ?? '').match(/\*/g)?.length).toBe(1);
  });

  it('mehrzeiliges Feld hat mindestens 4 Zeilen', () => {
    renderWithProviders(
      <TemplateForm fields={[field({ id: 'belegung', label: 'Belegung', multiline: true })]} values={{}} computed={null} onChange={() => {}} />,
    );
    const textarea = screen.getByLabelText('Belegung') as HTMLTextAreaElement;
    expect(Number(textarea.getAttribute('rows'))).toBeGreaterThanOrEqual(4);
  });

  it('leeres Zahlenfeld zeigt den Standardwert als Platzhalter (deutsches Komma)', () => {
    renderWithProviders(
      <TemplateForm fields={[field({ id: 'raster_mm', label: 'Portabstand (mm)', default_hint: '15.875' })]} values={{}} computed={null} onChange={() => {}} />,
    );
    expect(screen.getByLabelText('Portabstand (mm)')).toHaveAttribute('placeholder', 'Standard: 15,875');
  });

  it('Schriftgröße: Auswahl mit Klartext, liefert kanonischen Wert', async () => {
    const onChange = vi.fn();
    const { user } = renderWithProviders(<TemplateForm fields={[SIZE]} values={{ schriftgroesse: 'auto' }} computed={null} onChange={onChange} />);
    const dropdown = screen.getByRole('combobox', { name: 'Schriftgröße' });
    expect(dropdown).toHaveTextContent('Automatisch (einheitlich)');
    await user.click(dropdown);
    expect(await screen.findByRole('option', { name: 'Automatisch je Feld' })).toBeInTheDocument();
    await user.click(screen.getByRole('option', { name: '2,5 mm' }));
    expect(onChange).toHaveBeenCalledWith('schriftgroesse', '2.5');
  });

  it('Schriftgröße ohne „je Feld“ heißt nur „Automatisch“', () => {
    const plain = { ...SIZE, choices: ['auto', '2', '9'] };
    renderWithProviders(<TemplateForm fields={[plain]} values={{ schriftgroesse: 'auto' }} computed={null} onChange={() => {}} />);
    expect(screen.getByRole('combobox', { name: 'Schriftgröße' })).toHaveTextContent(/^Automatisch$/);
  });

  it('englisch: Beschriftung der Schriftgröße übersetzt', () => {
    renderWithProviders(<TemplateForm fields={[SIZE]} values={{ schriftgroesse: '2.5' }} computed={null} onChange={() => {}} />, { language: 'en' });
    expect(screen.getByRole('combobox', { name: 'Text size' })).toHaveTextContent('2.5 mm');
  });
});
