/** Druckablauf mit Fehldruckschutz: Rückfrage, Meldungen, Doppelstart-Sperre. */
import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../api/client';
import { cancelPrint, printLabel } from '../api/labels';
import { DEFAULT_PRINT_OPTIONS, type LabelSource, type OutcomeJson, type PrintOptions } from '../api/types';
import { useConfirm } from './ConfirmProvider';
import { useErrorText } from './ErrorMessage';
import { useNotify } from './NotifyProvider';

export interface PrintFlow<Req> {
  run(req: Req, options?: Partial<PrintOptions>): Promise<OutcomeJson | null>;
  busy: boolean;
  jobKey: string | null;
  last: OutcomeJson | null;
  cancel(): void;
}

function newJobKey(): string {
  return crypto.randomUUID();
}

export function usePrintFlow<Req>(
  send: (req: Req, options: PrintOptions) => Promise<OutcomeJson>,
  opts?: { onDone?: (o: OutcomeJson) => void },
): PrintFlow<Req> {
  const confirm = useConfirm();
  const notify = useNotify();
  const { t } = useTranslation('components');
  const errorText = useErrorText();
  const [busy, setBusy] = useState(false);
  const [jobKey, setJobKey] = useState<string | null>(null);
  const [last, setLast] = useState<OutcomeJson | null>(null);
  const busyRef = useRef(false);
  const jobKeyRef = useRef<string | null>(null);
  const sendRef = useRef(send);
  sendRef.current = send;
  const onDoneRef = useRef(opts?.onDone);
  onDoneRef.current = opts?.onDone;

  const report = useCallback(
    (o: OutcomeJson) => {
      const title = o.title || t('print.fallbackTitle');
      switch (o.status) {
        case 'ok': {
          const extra = [...o.warnings, o.balance_text].filter(Boolean).join('\n');
          notify({ intent: 'success', title: t('print.printed', { title }), body: extra || undefined });
          break;
        }
        case 'wartet':
          notify({ intent: 'warning', title: t('print.queued', { title }), body: o.warnings[0] ?? t('print.queuedBody') });
          break;
        case 'abgelehnt':
          notify({ intent: 'error', title: t('print.rejected'), body: o.reasons.join('\n') || undefined });
          break;
        case 'abgebrochen':
          notify({ intent: 'info', title: t('print.cancelled') });
          break;
        case 'unvollständig': // i18n-ignore (Server-Wert)
          notify({
            intent: 'error',
            title: t('print.incomplete'),
            body: o.error?.message ?? o.warnings[0] ?? t('print.incompleteBody'),
          });
          break;
        default:
          break;
      }
    },
    [notify, t],
  );

  const run = useCallback(
    async (req: Req, options?: Partial<PrintOptions>): Promise<OutcomeJson | null> => {
      if (busyRef.current) return null;
      busyRef.current = true;
      setBusy(true);
      const attempt = async (confirmed: boolean): Promise<OutcomeJson> => {
        const key = newJobKey();
        jobKeyRef.current = key;
        setJobKey(key);
        const merged: PrintOptions = { ...DEFAULT_PRINT_OPTIONS, ...options, confirmed: confirmed || Boolean(options?.confirmed), job_key: key };
        return sendRef.current(req, merged);
      };
      try {
        let outcome = await attempt(false);
        if (outcome.status === 'bestätigung_nötig') { // i18n-ignore (Server-Wert)
          const ok = await confirm({
            title: t('print.confirmTitle'),
            message: t('print.confirmMessage'),
            reasons: outcome.reasons,
            confirmText: t('print.confirmAction'),
            cancelText: t('print.confirmCancel'),
            danger: true,
          });
          if (!ok) {
            setLast(outcome);
            return outcome;
          }
          outcome = await attempt(true);
        }
        setLast(outcome);
        report(outcome);
        onDoneRef.current?.(outcome);
        return outcome;
      } catch (err) {
        if (err instanceof ApiError) {
          const e = errorText(err);
          notify({ intent: 'error', title: e.title, body: e.message || undefined, hint: e.hint || undefined });
        } else {
          notify({ intent: 'error', title: t('print.failed'), body: err instanceof Error ? err.message : String(err) });
        }
        return null;
      } finally {
        busyRef.current = false;
        jobKeyRef.current = null;
        setBusy(false);
        setJobKey(null);
      }
    },
    [confirm, notify, report, t, errorText],
  );

  const cancel = useCallback(() => {
    const key = jobKeyRef.current;
    if (key) void cancelPrint(key).catch(() => undefined);
  }, []);

  return { run, busy, jobKey, last, cancel };
}

export function usePrint(opts?: { onDone?: (o: OutcomeJson) => void }): PrintFlow<LabelSource> {
  return usePrintFlow<LabelSource>(printLabel, opts);
}
