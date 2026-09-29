import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { fixtures, mockApi } from '../test/utils';
import { setTokenForTests } from './client';
import { useLabelRender, type LabelRenderState } from './labels';
import type { LabelSource, RenderJson } from './types';

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

describe('useLabelRender', () => {
  it('mehrere schnelle Änderungen ergeben genau eine Anfrage nach der Entprellzeit', async () => {
    vi.useFakeTimers();
    setTokenForTests('t');
    const api = mockApi({ 'POST /api/v1/labels/render': ({ body }) => fixtures.renderJson({ title: JSON.stringify(body) }) });
    const { result, rerender } = renderHook(({ text }: { text: string }) => useLabelRender({ kind: 'text', lines: [text] }), {
      initialProps: { text: 'a' },
    });
    rerender({ text: 'ab' });
    rerender({ text: 'abc' });
    expect(result.current.loading).toBe(true);
    expect(result.current.renderedRevision).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(149);
    });
    expect(api.calls).toHaveLength(0);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    await flush();
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]?.body).toEqual({ source: { kind: 'text', lines: ['abc'] } });
    expect(result.current.loading).toBe(false);
    expect(result.current.renderedRevision).toBe(result.current.revision);
    expect(result.current.data?.title).toContain('abc');
  });

  it('gleiche Eingaben (JSON-Vergleich) lösen keine neue Anfrage aus', async () => {
    vi.useFakeTimers();
    setTokenForTests('t');
    const api = mockApi({ 'POST /api/v1/labels/render': () => fixtures.renderJson() });
    const { result, rerender } = renderHook(({ src }: { src: LabelSource }) => useLabelRender(src, undefined, { debounceMs: 10 }), {
      initialProps: { src: { kind: 'text', lines: ['x'] } as LabelSource },
    });
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await flush();
    const rev = result.current.revision;
    rerender({ src: { kind: 'text', lines: ['x'] } });
    await act(async () => {
      vi.advanceTimersByTime(50);
    });
    await flush();
    expect(result.current.revision).toBe(rev);
    expect(api.calls).toHaveLength(1);
  });

  it('veraltete Antwort überschreibt die neuere nicht', async () => {
    setTokenForTests('t');
    const resolvers: ((v: RenderJson) => void)[] = [];
    mockApi({
      'POST /api/v1/labels/render': () => new Promise<RenderJson>((resolve) => resolvers.push(resolve)),
    });
    const { result, rerender } = renderHook(({ text }: { text: string }) => useLabelRender({ kind: 'text', lines: [text] }, undefined, { debounceMs: 0 }), {
      initialProps: { text: 'alt' },
    });
    await vi.waitFor(() => expect(resolvers).toHaveLength(1));
    rerender({ text: 'neu' });
    await vi.waitFor(() => expect(resolvers).toHaveLength(2));
    await act(async () => {
      resolvers[1]?.(fixtures.renderJson({ title: 'neu' }));
    });
    await vi.waitFor(() => expect(result.current.data?.title).toBe('neu'));
    const state: LabelRenderState = result.current;
    await act(async () => {
      resolvers[0]?.(fixtures.renderJson({ title: 'alt' }));
    });
    await flush();
    expect(result.current.data?.title).toBe('neu');
    expect(result.current.renderedRevision).toBe(state.revision);
  });

  it('Fehler landet in error, source null macht nichts', async () => {
    setTokenForTests('t');
    const { MockResponse } = await import('../test/utils');
    const api = mockApi({
      'POST /api/v1/labels/render': () =>
        new MockResponse(422, { error: { kind: 'TemplateError', message: 'Vorlage kaputt', hint: '', exit_code: 6, details: null } }),
    });
    const { result, rerender } = renderHook(({ src }: { src: LabelSource | null }) => useLabelRender(src, undefined, { debounceMs: 0 }), {
      initialProps: { src: null as LabelSource | null },
    });
    await flush();
    expect(api.calls).toHaveLength(0);
    rerender({ src: { kind: 'template', template: 'x', values: {} } });
    await vi.waitFor(() => expect(result.current.error?.message).toBe('Vorlage kaputt'));
    expect(result.current.loading).toBe(false);
  });
});
