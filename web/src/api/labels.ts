/** Label-Endpunkte und der entprellte Vorschau-Hook. */
import { useEffect, useRef, useState } from 'react';
import { ApiError, apiDownload, apiPost } from './client';
import type { LabelSource, OutcomeJson, PrintOptions, RenderJson } from './types';

export function renderLabel(source: LabelSource, options?: Partial<PrintOptions>, signal?: AbortSignal): Promise<RenderJson> {
  return apiPost<RenderJson>('/api/v1/labels/render', options ? { source, options } : { source }, signal);
}

export function printLabel(source: LabelSource, options: PrintOptions): Promise<OutcomeJson> {
  return apiPost<OutcomeJson>('/api/v1/labels/print', { source, options });
}

export function cancelPrint(jobKey: string): Promise<{ cancelled: boolean }> {
  return apiPost<{ cancelled: boolean }>('/api/v1/print/cancel', { job_key: jobKey });
}

export function continueCut(): Promise<{ was_pausing: boolean }> {
  return apiPost<{ was_pausing: boolean }>('/api/v1/print/continue', {});
}

export function exportLabel(source: LabelSource, options: Partial<PrintOptions>, format: 'png' | 'pdf' | 'pbm'): Promise<void> {
  return apiDownload('/api/v1/labels/export', { source, options, format }, `label.${format}`, 'POST');
}

export interface LabelRenderState {
  data: RenderJson | undefined;
  loading: boolean;
  error: ApiError | null;
  revision: number;
  renderedRevision: number | null;
}

function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  const message = err instanceof Error ? err.message : String(err);
  return new ApiError(0, 'Error', message);
}

/**
 * Entprellte Vorschau: bei jeder Änderung von `source`/`options` (JSON-Vergleich) steigt `revision`;
 * nach der Entprellzeit geht genau eine Anfrage raus, veraltete werden abgebrochen.
 * `renderedRevision` ist die Revision der gezeigten Daten (Fehldruckschutz „Vorschau aktuell“).
 */
export function useLabelRender(
  source: LabelSource | null,
  options?: Partial<PrintOptions>,
  opts?: { debounceMs?: number },
): LabelRenderState {
  const debounceMs = opts?.debounceMs ?? 150;
  const key = source ? JSON.stringify([source, options ?? null]) : null;
  const [state, setState] = useState<LabelRenderState>({
    data: undefined,
    loading: false,
    error: null,
    revision: 0,
    renderedRevision: null,
  });
  const revisionRef = useRef(0);
  const latestInput = useRef<{ source: LabelSource | null; options?: Partial<PrintOptions> }>({ source, options });
  latestInput.current = { source, options };

  useEffect(() => {
    revisionRef.current += 1;
    const revision = revisionRef.current;
    const input = latestInput.current;
    if (!input.source) {
      setState((s) => ({ ...s, loading: false, error: null, revision }));
      return undefined;
    }
    setState((s) => ({ ...s, loading: true, revision }));
    const controller = new AbortController();
    const src = input.source;
    const timer = setTimeout(() => {
      renderLabel(src, input.options, controller.signal).then(
        (data) => {
          if (controller.signal.aborted || revision !== revisionRef.current) return;
          setState((s) => ({ ...s, data, loading: false, error: null, renderedRevision: revision }));
        },
        (err: unknown) => {
          if (controller.signal.aborted || revision !== revisionRef.current) return;
          if ((err as { name?: string } | null)?.name === 'AbortError') return;
          setState((s) => ({ ...s, loading: false, error: toApiError(err) }));
        },
      );
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, debounceMs]);

  return state;
}
