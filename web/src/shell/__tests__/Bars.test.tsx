import { describe, expect, it } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { FakeEventSource, mockApi, renderWithProviders } from '../../test/utils';
import { JobProgressBar } from '../JobProgressBar';
import { CutPauseBar } from '../CutPauseBar';

function emit(name: string, data: unknown) {
  act(() => FakeEventSource.latest()?.emit(name, data));
}

describe('JobProgressBar', () => {
  it('zeigt Fortschritt, „Abbrechen“ ruft cancel mit job_key, fertig blendet aus', async () => {
    const api = mockApi({ 'POST /api/v1/print/cancel': () => ({ cancelled: true }) });
    const { user } = renderWithProviders(<JobProgressBar />);
    expect(screen.queryByTestId('job-progress')).toBeNull();
    emit('job', { job_key: 'k1', phase: 'läuft', status: '', source: 'gui', title: '', queue_id: null });
    emit('progress', { job_key: 'k1', done: 50, total: 100 });
    expect(await screen.findByText(/50 %/)).toBeInTheDocument();
    expect(screen.getByText(/Label wird gedruckt/)).toBeInTheDocument();
    const bar = screen.getByRole('progressbar', { name: 'Druckfortschritt' });
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }));
    await waitFor(() => expect(api.calls).toContainEqual({ method: 'POST', path: '/api/v1/print/cancel', body: { job_key: 'k1' } }));
    emit('job', { job_key: 'k1', phase: 'fertig', status: 'ok' });
    expect(screen.queryByTestId('job-progress')).toBeNull();
  });

  it('Esc bricht ab, solange die Leiste sichtbar ist', async () => {
    const api = mockApi({ 'POST /api/v1/print/cancel': () => ({ cancelled: true }) });
    renderWithProviders(<JobProgressBar />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(api.calls).toHaveLength(1); // nur /app
    emit('job', { job_key: 'k2', phase: 'läuft' });
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/print/cancel')).toBe(true));
  });
});

describe('Englisch', () => {
  it('Fortschritt und Schneidpause übersetzt', async () => {
    mockApi({});
    renderWithProviders(
      <>
        <JobProgressBar />
        <CutPauseBar />
      </>,
      { language: 'en' },
    );
    emit('job', { job_key: 'k1', phase: 'läuft', title: 'Rack' });
    emit('progress', { job_key: 'k1', done: 1, total: 4 });
    expect(await screen.findByText('Rack: printing label … 25 %')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    emit('cut_pause', { job_key: 'k1', state: 'start', done: 1, total: 4, seconds: 0 });
    expect(await screen.findByText(/Cut off label 1\/4/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument();
  });
});

describe('CutPauseBar', () => {
  it('cut_pause start zeigt „Label 1/3 abschneiden“, Leertaste ruft continue', async () => {
    const api = mockApi({ 'POST /api/v1/print/continue': () => ({ was_pausing: true }) });
    renderWithProviders(<CutPauseBar />);
    emit('cut_pause', { job_key: 'k', state: 'start', done: 1, total: 3, seconds: 0 });
    expect(await screen.findByText(/Label 1\/3 abschneiden/)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: ' ', code: 'Space' });
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/print/continue')).toBe(true));
  });

  it('außerhalb der Pause löst die Leertaste nichts aus, end blendet aus', async () => {
    const api = mockApi({ 'POST /api/v1/print/continue': () => ({ was_pausing: true }) });
    const { user } = renderWithProviders(<CutPauseBar />);
    fireEvent.keyDown(window, { key: ' ', code: 'Space' });
    emit('cut_pause', { job_key: 'k', state: 'start', done: 2, total: 3, seconds: 5 });
    expect(await screen.findByText(/weiter in 5 s/)).toBeInTheDocument();
    emit('cut_pause', { job_key: 'k', state: 'end', done: 2, total: 3, seconds: 5 });
    expect(screen.queryByTestId('cut-pause')).toBeNull();
    fireEvent.keyDown(window, { key: ' ', code: 'Space' });
    await user.keyboard(' ');
    expect(api.calls.some((c) => c.path === '/api/v1/print/continue')).toBe(false);
  });

  it('Knopf „Weiter“ ruft continue', async () => {
    const api = mockApi({ 'POST /api/v1/print/continue': () => ({ was_pausing: true }) });
    const { user } = renderWithProviders(<CutPauseBar />);
    emit('cut_pause', { job_key: 'k', state: 'start', done: 1, total: 2, seconds: 0 });
    await user.click(await screen.findByRole('button', { name: 'Weiter' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/print/continue')).toBe(true));
  });
});
