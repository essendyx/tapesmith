/** Plausibilitätsprüfung vor dem Druck: Hinweise zu Werten einer Vorlage aus POST /homelab/plausi.
 *  Der Server blockiert nie; die Oberfläche zeigt Warnungen gelb und verlangt bei Konflikt eine
 *  ausdrückliche Bestätigung ("Trotzdem drucken", siehe Vorlagen/index.tsx). */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, MessageBar, MessageBarBody, MessageBarTitle, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { apiPost } from '../api/client';

export interface PlausiFinding {
  level: 'info' | 'warnung' | 'konflikt';
  field: string | null;
  code: string;
  message: string;
}

interface PlausiResponse {
  findings: PlausiFinding[];
  worst: PlausiFinding['level'] | null;
}

/** Felder, die eine Prüfung überhaupt auslösen: mindestens eines muss existieren und gefüllt sein. */
const RELEVANT_FIELDS = [
  'sn', 'seriennummer', 'serial', 'host', 'hostname', 'ip', 'ipv4', 'ip_kurz',
  'nummer', 'asset', 'asset_id', 'kabel_id',
];

function hasRelevantValue(values: Record<string, string>): boolean {
  return RELEVANT_FIELDS.some((f) => (values[f] ?? '').trim() !== '');
}

export interface PlausiResult {
  findings: PlausiFinding[];
  worst: PlausiFinding['level'] | null;
}

const EMPTY: PlausiResult = { findings: [], worst: null };

function postPlausi(template: string | null, values: Record<string, string>, signal?: AbortSignal): Promise<PlausiResult> {
  return apiPost<PlausiResponse>('/api/v1/homelab/plausi', { template, values, vault: false }, signal).then((res) => ({
    findings: res.findings,
    worst: res.worst,
  }));
}

/** Prüfung mit Entprellung für die Anzeige. `check()` liefert beim Drucken das Ergebnis für die
 *  aktuellen Werte: fertiges Ergebnis sofort, sonst wird die laufende bzw. entprellte Prüfung nicht
 *  abgewartet, sondern direkt neu angefragt. So wird ein Konflikt nie ohne Rückfrage gedruckt. */
export function usePlausi(
  template: string | null,
  values: Record<string, string>,
  opts?: { enabled?: boolean; debounceMs?: number },
): PlausiResult & { loading: boolean; check: () => Promise<PlausiResult> } {
  const enabled = opts?.enabled ?? true;
  const debounceMs = opts?.debounceMs ?? 600;
  const [findings, setFindings] = useState<PlausiFinding[]>([]);
  const [worst, setWorst] = useState<PlausiFinding['level'] | null>(null);
  const [loading, setLoading] = useState(false);

  const active = enabled && Boolean(template) && hasRelevantValue(values);
  const key = active ? JSON.stringify([template, values]) : null;
  const latest = useRef<{ template: string | null; values: Record<string, string>; key: string | null }>({
    template,
    values,
    key,
  });
  latest.current = { template, values, key };
  // Ergebnis je Schlüssel: nur ein Ergebnis zum aktuellen Schlüssel gilt als fertig.
  const done = useRef<{ key: string; result: PlausiResult } | null>(null);

  const apply = useCallback((k: string, result: PlausiResult) => {
    done.current = { key: k, result };
    if (latest.current.key !== k) return;
    setFindings(result.findings);
    setWorst(result.worst);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!key) {
      setFindings([]);
      setWorst(null);
      setLoading(false);
      return undefined;
    }
    if (done.current?.key === key) {
      setFindings(done.current.result.findings);
      setWorst(done.current.result.worst);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    const controller = new AbortController();
    const { template: t, values: v } = latest.current;
    const timer = setTimeout(() => {
      postPlausi(t, v, controller.signal).then(
        (res) => {
          if (controller.signal.aborted) return;
          apply(key, res);
        },
        (err: unknown) => {
          if (controller.signal.aborted) return;
          if ((err as { name?: string } | null)?.name === 'AbortError') return;
          // Fehler (404 bei älterem Dienst, 5xx, Netzfehler): still ignorieren, keine Meldung.
          apply(key, EMPTY);
        },
      );
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, debounceMs, apply]);

  const check = useCallback(async (): Promise<PlausiResult> => {
    const { template: t, values: v, key: k } = latest.current;
    if (!k) return EMPTY;
    if (done.current?.key === k) return done.current.result;
    try {
      const res = await postPlausi(t, v);
      apply(k, res);
      return res;
    } catch {
      apply(k, EMPTY);
      return EMPTY;
    }
  }, [apply]);

  return { findings, worst, loading, check };
}

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalXL },
});

export function PlausiHint(props: { findings: PlausiFinding[] }): JSX.Element | null {
  const styles = useStyles();
  const { t } = useTranslation('components');
  const [showInfo, setShowInfo] = useState(false);
  const { findings } = props;
  if (findings.length === 0) return null;

  const konflikt = findings.filter((f) => f.level === 'konflikt');
  const warnung = findings.filter((f) => f.level === 'warnung');
  const info = findings.filter((f) => f.level === 'info');

  return (
    <div className={styles.root}>
      {konflikt.length > 0 ? (
        <MessageBar intent="error" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>{t('plausi.conflict')}</MessageBarTitle>
            <ul className={styles.list}>
              {konflikt.map((f, i) => (
                <li key={`${f.code}-${i}`}>{f.message}</li>
              ))}
            </ul>
          </MessageBarBody>
        </MessageBar>
      ) : null}
      {warnung.length > 0 ? (
        <MessageBar intent="warning" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>{t('plausi.warning')}</MessageBarTitle>
            <ul className={styles.list}>
              {warnung.map((f, i) => (
                <li key={`${f.code}-${i}`}>{f.message}</li>
              ))}
            </ul>
          </MessageBarBody>
        </MessageBar>
      ) : null}
      {info.length > 0 ? (
        <>
          <Button appearance="subtle" size="small" onClick={() => setShowInfo((v) => !v)} aria-expanded={showInfo}>
            {showInfo ? t('plausi.hideNotes') : t('plausi.showNotes')}
          </Button>
          {showInfo ? (
            <MessageBar intent="info" layout="multiline">
              <MessageBarBody>
                <ul className={styles.list}>
                  {info.map((f, i) => (
                    <li key={`${f.code}-${i}`}>{f.message}</li>
                  ))}
                </ul>
              </MessageBarBody>
            </MessageBar>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
