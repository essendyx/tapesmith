import { describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { FakeEventSource, mockApi, renderWithProviders } from '../test/utils';
import { useEventsConnected, useServerEvent } from './events';
import { qk } from './core';

function ProgressProbe() {
  const [text, setText] = useState('');
  const connected = useEventsConnected();
  useServerEvent<{ done: number; total: number }>('progress', (d) => setText(`${d.done}/${d.total}`));
  return (
    <>
      <output data-testid="progress">{text}</output>
      <output data-testid="connected">{connected ? 'ja' : 'nein'}</output>
    </>
  );
}

describe('ServerEventsProvider', () => {
  it('öffnet eine EventSource mit Token in der URL', () => {
    mockApi({}, { quiet: true });
    renderWithProviders(<ProgressProbe />);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.latest()?.url).toBe('/api/v1/events?lang=de&t=test-token');
  });

  it('useServerEvent bekommt progress-Daten', async () => {
    mockApi({}, { quiet: true });
    renderWithProviders(<ProgressProbe />);
    act(() => FakeEventSource.latest()?.emit('progress', { job_key: 'a', done: 5, total: 10 }));
    await waitFor(() => expect(screen.getByTestId('progress')).toHaveTextContent('5/10'));
    expect(screen.getByTestId('connected')).toHaveTextContent('ja');
  });

  it('job fertig invalidiert Verlauf, Warteschlange, Statistik, Rollen', () => {
    mockApi({}, { quiet: true });
    const { queryClient } = renderWithProviders(<ProgressProbe />);
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => FakeEventSource.latest()?.emit('job', { job_key: 'a', phase: 'läuft' }));
    expect(spy).not.toHaveBeenCalled();
    act(() => FakeEventSource.latest()?.emit('job', { job_key: 'a', phase: 'fertig', status: 'ok' }));
    const keys = spy.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(qk.history);
    expect(keys).toContainEqual(qk.queue);
    expect(keys).toContainEqual(qk.stats);
    expect(keys).toContainEqual(qk.rolls);
    expect(keys).toContainEqual(qk.recentTexts);
  });

  it('status, queue und config invalidieren ihre Schlüssel', () => {
    mockApi({}, { quiet: true });
    const { queryClient } = renderWithProviders(<ProgressProbe />);
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => FakeEventSource.latest()?.emit('status', {}));
    act(() => FakeEventSource.latest()?.emit('queue', {}));
    act(() => FakeEventSource.latest()?.emit('config', { keys: ['tape'] }));
    const keys = spy.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toEqual([qk.status, qk.queue, qk.app, qk.settings, qk.tapes, ['access'], ['secrets']]);
  });

  it('verbindet nach Fehler mit Backoff neu und invalidiert dann alles', () => {
    vi.useFakeTimers();
    try {
      mockApi({}, { quiet: true });
      const { queryClient } = renderWithProviders(<ProgressProbe />);
      act(() => FakeEventSource.latest()?.open());
      const spy = vi.spyOn(queryClient, 'invalidateQueries');
      act(() => FakeEventSource.latest()?.fail());
      expect(screen.getByTestId('connected')).toHaveTextContent('nein');
      act(() => {
        vi.advanceTimersByTime(999);
      });
      expect(FakeEventSource.instances).toHaveLength(1);
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(FakeEventSource.instances).toHaveLength(2);
      act(() => FakeEventSource.latest()?.fail());
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(FakeEventSource.instances).toHaveLength(3);
      act(() => FakeEventSource.latest()?.emit('hello', { version: '1', home_key: 'x' }));
      expect(spy).toHaveBeenCalledWith();
      expect(screen.getByTestId('connected')).toHaveTextContent('ja');
    } finally {
      vi.useRealTimers();
    }
  });

  it('Verbindungsabbruch lässt die App-Info einmal neu prüfen (Dienst weg oder neues Token)', () => {
    vi.useFakeTimers();
    try {
      mockApi({}, { quiet: true });
      const { queryClient } = renderWithProviders(<ProgressProbe />);
      act(() => FakeEventSource.latest()?.open());
      const spy = vi.spyOn(queryClient, 'invalidateQueries');
      act(() => FakeEventSource.latest()?.fail());
      expect(spy.mock.calls.map((c) => c[0]?.queryKey)).toEqual([qk.app]);
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      act(() => FakeEventSource.latest()?.fail());
      expect(spy).toHaveBeenCalledTimes(1);      // weitere Fehlversuche prüfen nicht erneut
    } finally {
      vi.useRealTimers();
    }
  });

  it('ohne Token keine Verbindung', () => {
    mockApi({}, { quiet: true });
    renderWithProviders(<ProgressProbe />, { token: null });
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
