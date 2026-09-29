import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { fixtures, mockApi, renderWithProviders } from '../../test/utils';
import { FIT_MAX_HEIGHT, FIT_MAX_HEIGHT_COMPACT, TapePreview } from '../TapePreview';
import { PrintOptionsBar } from '../PrintOptionsBar';
import { WarningList } from '../WarningList';
import { DEFAULT_PRINT_OPTIONS, type PrintOptions } from '../../api/types';

const DESIGN = 'RGVzaWdu';
const RASTER = 'UmFzdGVy';

function render100() {
  const base = fixtures.renderJson();
  return fixtures.renderJson({
    title: 'Kabel',
    preview: { ...base.preview!, design_png: DESIGN, raster_png: RASTER, width: 200, info: '25 mm · 1 Label' },
  });
}

describe('TapePreview', () => {
  it('zeigt das Design-Bild, Umschalten auf Druckbild wechselt src', async () => {
    mockApi({});
    const { user } = renderWithProviders(<TapePreview render={render100()} />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('src', `data:image/png;base64,${DESIGN}`);
    expect(img.getAttribute('alt')).toMatch(/^Vorschau: Kabel/);
    // Info-Zeile entsteht clientseitig aus den Zahlen (content_mm 25, tape_mm 35)
    expect(img.getAttribute('alt')).toContain('Inhalt 25 mm + Vor-/Nachlauf 10 mm = 35 mm Band');
    await user.click(screen.getByRole('tab', { name: 'Druckbild' }));
    expect(screen.getByRole('img')).toHaveAttribute('src', `data:image/png;base64,${RASTER}`);
  });

  it("zoom '100' mit 4 px/mm und 8 Punkten/mm ergibt halbe Breite", async () => {
    mockApi({});
    renderWithProviders(<TapePreview render={render100()} zoom="100" />, { app: { screen_px_per_mm: 4 } });
    await waitFor(() => expect(screen.getByRole('img').style.width).toBe('100px'));
    expect(screen.queryByText(/nicht kalibriert/)).toBeNull();
  });

  it('ohne Kalibrierung Hinweis „nicht kalibriert“', async () => {
    mockApi({});
    renderWithProviders(<TapePreview render={render100()} zoom="100" />, { app: { screen_px_per_mm: null } });
    expect(await screen.findByText(/nicht kalibriert/)).toBeInTheDocument();
  });

  it('fit begrenzt auf Faktor 6, compact ohne Umschalter, Fehler und Warnungen darunter', () => {
    mockApi({});
    const r = fixtures.renderJson({ errors: ['Text zu lang'], warnings: ['Kontrast gering'] });
    renderWithProviders(<TapePreview render={r} compact loading />);
    expect(screen.queryByRole('tab')).toBeNull();
    expect(screen.getByRole('img').style.maxWidth).toBe(`${r.preview!.width * 6}px`);
    expect(screen.getByText('Text zu lang')).toBeInTheDocument();
    expect(screen.getByText('Kontrast gering')).toBeInTheDocument();
  });

  it('ohne Daten Platzhalter', () => {
    mockApi({});
    renderWithProviders(<TapePreview render={undefined} />);
    expect(screen.getByText('Noch keine Vorschau')).toBeInTheDocument();
  });
});

/** Vorschau mit 38 mm Inhalt und 48 mm Band (geschätzt), drei Labels. */
function render38(o?: { estimated?: boolean; labels?: number }) {
  const base = fixtures.renderJson();
  return fixtures.renderJson({
    title: 'Regal',
    preview: {
      ...base.preview!,
      content_mm: 38,
      tape_mm: 48,
      estimated: o?.estimated ?? true,
      labels: o?.labels ?? 1,
      info: 'Serverinfo',
    },
  });
}

describe('TapePreview', () => {
  it('Einpassen passt in Breite und Höhe ein: maxHeight und objectFit gesetzt, Klasse für Kontrastdesigns', async () => {
    mockApi({});
    const { user } = renderWithProviders(<TapePreview render={render38()} onZoomChange={() => undefined} />);
    const img = screen.getByRole('img');
    expect(img.style.maxHeight).toBe(FIT_MAX_HEIGHT);
    expect(img.style.objectFit).toBe('contain');
    expect(img).toHaveClass('p12-tape-image');
    await user.click(screen.getByRole('button', { name: '100 %' }));
    expect(screen.getByRole('img').style.maxHeight).toBe('none');
    await user.click(screen.getByRole('button', { name: 'Einpassen' }));
    expect(screen.getByRole('img').style.objectFit).toBe('contain');
  });

  it('kompakt: niedrige Bühne und keine Werkzeugleiste', () => {
    mockApi({});
    renderWithProviders(<TapePreview render={render38()} compact />);
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.queryByRole('group', { name: 'Zoom' })).toBeNull();
    expect(screen.getByRole('img').style.maxHeight).toBe(FIT_MAX_HEIGHT_COMPACT);
  });

  it('Info-Zeile Deutsch aus den Zahlen, „ca.“ nur bei Schätzung, Bandname aus AppInfo', async () => {
    mockApi({});
    const { unmount } = renderWithProviders(<TapePreview render={render38({ labels: 3 })} />);
    const info = screen.getByTestId('preview-info');
    expect(info).toHaveTextContent('Inhalt 38 mm + Vor-/Nachlauf ca. 10 mm = ca. 48 mm Band');
    expect(info).toHaveTextContent('3 Labels: 48 mm Band');
    expect(await screen.findByText('Band: Weiß 12 mm')).toBeInTheDocument();
    expect(info).not.toHaveTextContent('Serverinfo');
    unmount();
    renderWithProviders(<TapePreview render={render38({ estimated: false })} />);
    expect(screen.getByTestId('preview-info')).toHaveTextContent('Inhalt 38 mm + Vor-/Nachlauf 10 mm = 48 mm Band');
  });

  it('Englisch: Info-Zeile, Umschalter und alt-Text übersetzt', async () => {
    mockApi({});
    renderWithProviders(<TapePreview render={render38()} onZoomChange={() => undefined} />, { language: 'en' });
    expect(screen.getByTestId('preview-info')).toHaveTextContent('Content 38 mm');
    expect(screen.getByRole('tab', { name: 'Print image' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fit' })).toBeInTheDocument();
    const alt = screen.getByRole('img').getAttribute('alt') ?? '';
    expect(alt).toMatch(/^Preview: Regal\. Content 38 mm/);
  });

  it('alt-Text Deutsch mit Titel und Druckbild-Zusatz', async () => {
    mockApi({});
    const { user } = renderWithProviders(<TapePreview render={render38()} />);
    expect(screen.getByRole('img').getAttribute('alt')).toMatch(/^Vorschau: Regal\. Inhalt 38 mm/);
    await user.click(screen.getByRole('tab', { name: 'Druckbild' }));
    expect(screen.getByRole('img').getAttribute('alt')).toMatch(/^Vorschau: Regal \(Druckbild\)\./);
  });
});

function OptionsHarness() {
  const [value, setValue] = useState<PrintOptions>(DEFAULT_PRINT_OPTIONS);
  return (
    <>
      <PrintOptionsBar value={value} onChange={setValue} />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

describe('PrintOptionsBar', () => {
  it('Kette schaltet Schnittmarken frei, Schneidpause wählt Werte', async () => {
    mockApi({});
    const { user } = renderWithProviders(<OptionsHarness />);
    expect(screen.queryByRole('switch', { name: 'Schnittmarken' })).toBeNull();
    await user.click(screen.getByRole('switch', { name: 'Als Kette' }));
    expect(screen.getByRole('switch', { name: 'Schnittmarken' })).toBeChecked();
    await user.click(screen.getByRole('combobox', { name: 'Schneidpause' }));
    await user.click(await screen.findByRole('option', { name: '10 s' }));
    const v = JSON.parse(screen.getByTestId('value').textContent ?? '{}') as PrintOptions;
    expect(v.chain).toBe(true);
    expect(v.cut_pause_s).toBe(10);
  });

  it('Kopien per SpinButton', async () => {
    mockApi({});
    const { user } = renderWithProviders(<OptionsHarness />);
    const spin = screen.getByRole('spinbutton', { name: 'Kopien' });
    await user.click(spin);
    await user.keyboard('{ArrowUp}{ArrowUp}');
    const v = JSON.parse(screen.getByTestId('value').textContent ?? '{}') as PrintOptions;
    expect(v.copies).toBe(3);
  });
});

describe('WarningList', () => {
  it('nennt die Art als Text, nicht nur über Farbe', () => {
    mockApi({});
    renderWithProviders(<WarningList errors={['A']} warnings={['B']} notes={['C']} />);
    expect(screen.getByText('Fehler:', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Warnung:', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Hinweis:', { exact: false })).toBeInTheDocument();
  });
});
