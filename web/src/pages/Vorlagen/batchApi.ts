/** Serien-/Import-Endpunkte: Tabelle einlesen, Plan berechnen, drucken, Kontaktabzug. */
import { apiDownload, apiPost } from '../../api/client';
import type {
  BatchPlanJson,
  BatchRequest,
  BatchTableJson,
  BatchTableRequest,
  OutcomeJson,
  PrintOptions,
} from '../../api/types';

export function fetchBatchTable(source: BatchTableRequest['source']): Promise<BatchTableJson> {
  return apiPost<BatchTableJson>('/api/v1/batch/table', { source });
}

export function fetchBatchPlan(req: BatchRequest, signal?: AbortSignal): Promise<BatchPlanJson> {
  return apiPost<BatchPlanJson>('/api/v1/batch/plan', req, signal);
}

export function printBatch(req: BatchRequest, options: PrintOptions): Promise<OutcomeJson> {
  return apiPost<OutcomeJson>('/api/v1/batch/print', { ...req, options });
}

export function batchContactSheet(req: BatchRequest): Promise<void> {
  return apiDownload('/api/v1/batch/contact-sheet', req, 'kontaktabzug.png', 'POST');
}
