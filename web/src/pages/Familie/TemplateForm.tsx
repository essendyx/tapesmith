/** Formular einer Vorlage: Felder, entprellte Vorschau, Kopien, Drucken mit Rückfrage-Dialog. */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Body1,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Select,
  Textarea,
  Title2,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowLeft24Regular, Add24Regular, Subtract24Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { FamilyError, postPreview, postPrint } from './familyClient';
import { PreviewCard } from './PreviewCard';
import type { FamilyField, FamilyPreview, FamilyPrintResult, FamilyTemplate } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

const PREVIEW_DEBOUNCE_MS = 400;

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  header: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
  back: { minWidth: '40px' },
  field: { '& textarea, & input, & select': { fontSize: '16px' } },
  copiesRow: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalM },
  copiesBtn: { minWidth: '48px', minHeight: '48px', fontSize: tokens.fontSizeBase500 },
  copiesValue: { minWidth: '32px', textAlign: 'center', fontSize: tokens.fontSizeBase500 },
  printBtn: { width: '100%', minHeight: '56px', fontSize: tokens.fontSizeBase500 },
  messageOk: { color: tokens.colorPaletteGreenForeground1, fontWeight: tokens.fontWeightSemibold },
  messageInfo: { color: tokens.colorBrandForeground1 },
  messageError: { color: tokens.colorPaletteRedForeground1 },
});

function initialValues(template: FamilyTemplate): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of template.fields) out[f.id] = f.default ?? '';
  return out;
}

function requiredMissing(template: FamilyTemplate, values: Record<string, string>): boolean {
  return template.fields.some((f) => f.required && !(values[f.id] ?? '').trim());
}

type ResultKind = 'ok' | 'info' | 'error';

function statusToKind(status: FamilyPrintResult['status']): ResultKind {
  if (status === 'ok') return 'ok'; // i18n-ignore (Server-Wert)
  if (status === 'wartet') return 'info'; // i18n-ignore (Server-Wert)
  return 'error';
}

export function TemplateForm(props: {
  template: FamilyTemplate;
  maxCopies: number;
  onBack: () => void;
  onAuthError: (status: number) => void;
}): JSX.Element {
  const { template, maxCopies, onBack, onAuthError } = props;
  const styles = useStyles();
  const { t } = useTranslation('familie');
  // Keine Verbindung (Status 0) meldet der Client selbst auf Deutsch: hier übersetzt anzeigen.
  const failureText = (err: unknown, fallback: string): string =>
    err instanceof FamilyError && err.status === 0 ? t('form.offline') : err instanceof Error ? err.message : fallback;
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(template));
  const [copies, setCopies] = useState(1);
  const [preview, setPreview] = useState<FamilyPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [printing, setPrinting] = useState(false);
  const [result, setResult] = useState<{ kind: ResultKind; text: string } | null>(null);
  const [confirmState, setConfirmState] = useState<{ message: string; reasons: string[] } | null>(null);
  // Bleibt über setField-Resets von `result` hinweg bestehen, solange dieselbe Vorlage offen ist:
  // sobald einmal erfolgreich gedruckt wurde, bleibt „Fertig" zusätzlich zum Drucken-Knopf sichtbar.
  const [printedOnce, setPrintedOnce] = useState(false);
  const seqRef = useRef(0);
  const skipRef = useRef(true);
  useDialogFocusReturn(confirmState !== null);

  useEffect(() => {
    skipRef.current = true;
    setValues(initialValues(template));
    setCopies(1);
    setPreview(null);
    setPreviewLoading(false);
    setResult(null);
    setConfirmState(null);
    setPrintedOnce(false);
    // Neue Vorlage: kein sofortiger Vorschau-Aufruf, nur bei tatsächlicher Eingabe.
  }, [template]);

  useEffect(() => {
    if (skipRef.current) {
      skipRef.current = false;
      return undefined;
    }
    const mySeq = ++seqRef.current;
    setPreviewLoading(true);
    const timer = setTimeout(() => {
      void postPreview(template.name, values)
        .then((p) => {
          if (seqRef.current !== mySeq) return;
          setPreview(p);
          setPreviewLoading(false);
        })
        .catch((err: unknown) => {
          if (seqRef.current !== mySeq) return;
          setPreviewLoading(false);
          if (err instanceof FamilyError && (err.status === 401 || err.status === 403 || err.status === 429)) {
            onAuthError(err.status);
            return;
          }
          setPreview({ ok: false, errors: [failureText(err, t('preview.failed'))], warnings: [], design_png: null, width: null, height: null, length_mm: null });
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, template.name]);

  const setField = (id: string, v: string) => {
    // Nach einer Bearbeitung ist eine frühere Rückmeldung ("Gedruckt.", Fehler, ...) nicht mehr
    // aktuell: zurücksetzen, damit wieder der Drucken-Knopf erscheint (Fertig bleibt via
    // `printedOnce` zusätzlich verfügbar, wenn in dieser Vorlage schon einmal gedruckt wurde).
    setResult(null);
    setConfirmState(null);
    setValues((prev) => ({ ...prev, [id]: v }));
  };

  const missingRequired = useMemo(() => requiredMissing(template, values), [template, values]);
  const canPrint = !missingRequired && preview?.ok === true && !printing;

  async function runPrint(confirmed: boolean): Promise<void> {
    if (printing) return;
    setPrinting(true);
    try {
      const res = await postPrint(template.name, values, copies, confirmed);
      if (res.status === 'bestätigung_nötig') { // i18n-ignore (Server-Wert)
        setConfirmState({ message: res.message, reasons: res.reasons });
        return;
      }
      setConfirmState(null);
      setResult({ kind: statusToKind(res.status), text: res.status === 'ok' ? t('form.printed') : res.message }); // i18n-ignore (Server-Wert)
      if (res.status === 'ok') setPrintedOnce(true); // i18n-ignore (Server-Wert)
    } catch (err) {
      if (err instanceof FamilyError && (err.status === 401 || err.status === 403 || err.status === 429)) {
        onAuthError(err.status);
        return;
      }
      setResult({ kind: 'error', text: failureText(err, t('form.printFailed')) });
    } finally {
      setPrinting(false);
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <Button className={styles.back} appearance="subtle" icon={<ArrowLeft24Regular />} aria-label={t('form.back')} onClick={onBack} />
        <Title2 as="h2">{template.title}</Title2>
      </div>

      {template.fields.map((f) => (
        <FieldInput key={f.id} className={styles.field} field={f} value={values[f.id] ?? ''} sample={template.sample[f.id]} onChange={(v) => setField(f.id, v)} />
      ))}

      <PreviewCard preview={preview} loading={previewLoading} />

      <div className={styles.copiesRow}>
        <Button
          className={styles.copiesBtn}
          icon={<Subtract24Regular />}
          aria-label={t('form.fewerCopies')}
          disabled={copies <= 1}
          onClick={() => setCopies((c) => Math.max(1, c - 1))}
        />
        <span className={styles.copiesValue}>{copies}</span>
        <Button
          className={styles.copiesBtn}
          icon={<Add24Regular />}
          aria-label={t('form.moreCopies')}
          disabled={copies >= maxCopies}
          onClick={() => setCopies((c) => Math.min(maxCopies, c + 1))}
        />
      </div>

      {result && result.kind === 'ok' ? (
        <>
          <Body1 role="status" className={styles.messageOk}>
            {result.text}
          </Body1>
          <Button appearance="secondary" onClick={onBack}>
            {t('form.done')}
          </Button>
        </>
      ) : (
        <>
          <Button className={styles.printBtn} appearance="primary" disabled={!canPrint} onClick={() => void runPrint(false)}>
            {t('form.print')}
          </Button>
          {printedOnce ? (
            <Button appearance="secondary" onClick={onBack}>
              {t('form.done')}
            </Button>
          ) : null}
        </>
      )}

      {result && result.kind !== 'ok' ? (
        <Body1 role="status" className={result.kind === 'info' ? styles.messageInfo : styles.messageError}>
          {result.text}
        </Body1>
      ) : null}

      <Dialog open={confirmState !== null} onOpenChange={(_e, data) => (!data.open ? setConfirmState(null) : undefined)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('form.confirmTitle')}</DialogTitle>
            <DialogContent>
              <p>{confirmState?.message}</p>
              {confirmState && confirmState.reasons.length > 0 ? (
                <ul>
                  {confirmState.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : null}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={printing} onClick={() => void runPrint(true)}>
                {t('form.confirmAction')}
              </Button>
              <Button appearance="secondary" onClick={() => setConfirmState(null)}>
                {t('form.confirmCancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}

function FieldInput(props: {
  className: string;
  field: FamilyField;
  value: string;
  sample: string | undefined;
  onChange: (v: string) => void;
}): JSX.Element {
  const { field, value, sample, onChange } = props;
  const { t } = useTranslation('familie');
  const label = field.required ? t('form.labelRequired', { label: field.label }) : field.label;

  let control: JSX.Element;
  if (field.choices.length > 0) {
    control = (
      <Select value={value} onChange={(_e, data) => onChange(data.value)} aria-label={label}>
        <option value="" disabled hidden>
          {t('form.chooseOption')}
        </option>
        {field.choices.map((c) => (
          <option key={c} value={c}>
            {field.choice_labels?.[c] ?? c}
          </option>
        ))}
      </Select>
    );
  } else if (field.multiline) {
    control = <Textarea value={value} onChange={(_e, data) => onChange(data.value)} aria-label={label} maxLength={field.max_len ?? undefined} />;
  } else if (field.type === 'date') {
    control = (
      <Input
        value={value}
        onChange={(_e, data) => onChange(data.value)}
        aria-label={label}
        placeholder={sample ?? t('form.datePlaceholder')}
        maxLength={field.max_len ?? undefined}
      />
    );
  } else {
    control = (
      <Input
        value={value}
        onChange={(_e, data) => onChange(data.value)}
        aria-label={label}
        maxLength={field.max_len ?? undefined}
      />
    );
  }

  return (
    // Pflichtfelder sind schon im Label-Text markiert (label enthält „ *"); Field bekommt kein
    // eigenes `required`, sonst zeigt es einen zweiten, redundanten Stern.
    <Field className={props.className} label={label}>
      {control}
    </Field>
  );
}
