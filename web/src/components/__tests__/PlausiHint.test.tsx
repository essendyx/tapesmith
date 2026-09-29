import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, screen } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import { setTokenForTests } from '../../api/client';
import { PlausiHint, usePlausi, type PlausiFinding } from '../PlausiHint';

afterEach(() => {
  vi.useRealTimers();
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

const KONFLIKT: PlausiFinding = { level: 'konflikt', field: 'sn', code: 'sn_anderer_host', message: 'SN gehört zu pmx20' };
const WARNUNG: PlausiFinding = { level: 'warnung', field: 'ip', code: 'ip_ausserhalb', message: 'IP liegt außerhalb' };
const INFO: PlausiFinding = { level: 'info', field: 'sn', code: 'sn_unbekannt', message: 'SN unbekannt' };

describe('PlausiHint', () => {
  it('rendert Konflikt und Warnung offen, Info eingeklappt hinter "Hinweise anzeigen"', async () => {
    const { user } = renderWithProviders(<PlausiHint findings={[KONFLIKT, WARNUNG, INFO]} />);
    expect(screen.getByText('Konflikt bei der Prüfung')).toBeInTheDocument();
    expect(screen.getByText('SN gehört zu pmx20')).toBeInTheDocument();
    expect(screen.getByText('IP liegt außerhalb')).toBeInTheDocument();
    expect(screen.queryByText('SN unbekannt')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Hinweise anzeigen' }));
    expect(screen.getByText('SN unbekannt')).toBeInTheDocument();
  });

  it('ohne Befunde wird nichts gerendert', () => {
    const { container } = renderWithProviders(<PlausiHint findings={[]} />);
    expect(container.textContent).toBe('');
  });
});

describe('usePlausi', () => {
  it('sendet nach der Entprellung genau einen POST mit template und values', async () => {
    vi.useFakeTimers();
    setTokenForTests('t');
    const api = mockApi({ 'POST /api/v1/homelab/plausi': () => ({ findings: [KONFLIKT], worst: 'konflikt' }) });
    const { result, rerender } = renderHook(
      ({ values }: { values: Record<string, string> }) => usePlausi('datentraeger', values, { debounceMs: 100 }),
      { initialProps: { values: { sn: 'a' } } },
    );
    rerender({ values: { sn: 'ab' } });
    rerender({ values: { sn: 'abc' } });
    expect(result.current.loading).toBe(true);
    await act(async () => {
      vi.advanceTimersByTime(99);
    });
    expect(api.calls).toHaveLength(0);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    await flush();
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]?.body).toEqual({ template: 'datentraeger', values: { sn: 'abc' }, vault: false });
    expect(result.current.findings).toEqual([KONFLIKT]);
    expect(result.current.worst).toBe('konflikt');
    expect(result.current.loading).toBe(false);
  });

  it('check() wartet nicht auf die Entprellung, prüft sofort und merkt sich das Ergebnis', async () => {
    setTokenForTests('t');
    const api = mockApi({ 'POST /api/v1/homelab/plausi': () => ({ findings: [KONFLIKT], worst: 'konflikt' }) });
    const { result } = renderHook(() => usePlausi('datentraeger', { sn: 'abc' }, { debounceMs: 60_000 }));
    expect(api.calls).toHaveLength(0);
    let checked: Awaited<ReturnType<typeof result.current.check>> | undefined;
    await act(async () => {
      checked = await result.current.check();
    });
    expect(checked).toEqual({ findings: [KONFLIKT], worst: 'konflikt' });
    expect(api.calls).toHaveLength(1);
    expect(result.current.worst).toBe('konflikt');

    await act(async () => {
      checked = await result.current.check();
    });
    expect(checked?.worst).toBe('konflikt');
    expect(api.calls).toHaveLength(1);
  });

  it('check() ohne relevante Felder fragt nicht und meldet nichts', async () => {
    setTokenForTests('t');
    const api = mockApi({ 'POST /api/v1/homelab/plausi': () => ({ findings: [KONFLIKT], worst: 'konflikt' }) });
    const { result } = renderHook(() => usePlausi('datentraeger', { notiz: 'x' }));
    let checked: Awaited<ReturnType<typeof result.current.check>> | undefined;
    await act(async () => {
      checked = await result.current.check();
    });
    expect(checked).toEqual({ findings: [], worst: null });
    expect(api.calls).toHaveLength(0);
  });

  it('Vorlage ohne passende Felder sendet nichts', async () => {
    vi.useFakeTimers();
    setTokenForTests('t');
    const api = mockApi({ 'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }) });
    renderHook(() => usePlausi('datentraeger', { notiz: 'kein plausi-feld' }, { debounceMs: 10 }));
    await act(async () => {
      vi.advanceTimersByTime(50);
    });
    await flush();
    expect(api.calls).toHaveLength(0);
  });

  it('Fehler (404) ergibt keine Anzeige', async () => {
    vi.useFakeTimers();
    setTokenForTests('t');
    mockApi({}, { quiet: true });
    const { result } = renderHook(() => usePlausi('datentraeger', { sn: 'abc' }, { debounceMs: 10 }));
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await flush();
    expect(result.current.findings).toEqual([]);
    expect(result.current.worst).toBeNull();
  });
});
