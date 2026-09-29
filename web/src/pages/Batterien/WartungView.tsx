/** Reiter „Wartung“: Formular mit Live-Vorschau, Drucken und optionalem HA-To-do. */
import { useState } from 'react';
import {
  Button,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Switch,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { pngSrc } from '../../api/client';
import { useLabelRender, printLabel } from '../../api/labels';
import type { LabelSource } from '../../api/types';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { useFormat } from '../../i18n/format';
import { usePrintFlow } from '../../components/usePrint';
import { postTodo, useBatteries } from './api';
import { WARTUNG_SUGGESTIONS } from './types';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, maxWidth: '480px' },
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  suggestions: {
    display: 'flex',
    flexWrap: 'wrap',
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXS,
  },
  preview: { maxWidth: '260px', borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow4 },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap', alignItems: 'center' },
  muted: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
});

function todayText(): string {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
}

/** Monatsaddition mit Tageskappung, wie `integrations.homeassistant.due_date`. */
function addMonths(text: string, months: number): string {
  const parts = text.split('.');
  if (parts.length !== 3) return '';
  const [dd, mm, yyyy] = parts.map(Number);
  if (!dd || !mm || !yyyy) return '';
  const totalMonth = mm - 1 + months;
  const year = yyyy + Math.floor(totalMonth / 12);
  const month = ((totalMonth % 12) + 12) % 12;
  const lastDay = new Date(year, month + 1, 0).getDate();
  const day = Math.min(dd, lastDay);
  return `${String(day).padStart(2, '0')}.${String(month + 1).padStart(2, '0')}.${year}`;
}

function toIso(text: string): string {
  const [dd, mm, yyyy] = text.split('.');
  return dd && mm && yyyy ? `${yyyy}-${mm}-${dd}` : '';
}

export function WartungView(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('batterien');
  const { formatDate } = useFormat();
  const [was, setWas] = useState('');
  const [datum, setDatum] = useState(todayText());
  const [intervall, setIntervall] = useState('12');
  const [notiz, setNotiz] = useState('');
  const [reminder, setReminder] = useState(false);
  const [todoOk, setTodoOk] = useState(false);
  const [todoError, setTodoError] = useState<unknown>(null);

  const batteries = useBatteries();
  const todoEntity = batteries.data?.todo_entity ?? null;

  const source: LabelSource | null =
    was.trim() !== '' && datum.trim() !== ''
      ? { kind: 'template', template: 'wartung', values: { was, datum, intervall, notiz } }
      : null;
  const render = useLabelRender(source);

  const printFlow = usePrintFlow<LabelSource>((req, opts) => printLabel(req, opts), {
    onDone: (outcome) => {
      if (outcome.status !== 'ok' || !reminder || !todoEntity) return;
      setTodoError(null);
      setTodoOk(false);
      postTodo({
        item: `Wartung: ${was}`, // i18n-ignore (Text im Home-Assistant-To-do, nicht die Oberfläche)
        due: toIso(addMonths(datum, Number(intervall) || 0)),
        description: notiz,
      })
        .then(() => setTodoOk(true))
        .catch((err: unknown) => setTodoError(err));
    },
  });

  function applySuggestion(id: string, months: number): void {
    setWas(t(`wartung.suggestions.${id}`));
    setIntervall(String(months));
  }

  const canPrint = source !== null && !printFlow.busy;
  const dueIso = datum.trim() !== '' ? toIso(addMonths(datum, Number(intervall) || 0)) : '';

  return (
    <div className={styles.root}>
      <div className={styles.suggestions}>
        {WARTUNG_SUGGESTIONS.map((s) => (
          <Button key={s.id} size="small" onClick={() => applySuggestion(s.id, s.months)}>
            {t(`wartung.suggestions.${s.id}`)}
          </Button>
        ))}
      </div>

      <div className={styles.grid}>
        <Field label={t('wartung.wasLabel')} required>
          <Input value={was} onChange={(_e, d) => setWas(d.value)} />
        </Field>
        <Field label={t('wartung.datumLabel')} required>
          <Input value={datum} onChange={(_e, d) => setDatum(d.value)} />
        </Field>
        <Field label={t('wartung.intervallLabel')}>
          <Input value={intervall} onChange={(_e, d) => setIntervall(d.value)} inputMode="numeric" />
        </Field>
        <Field label={t('wartung.notizLabel')}>
          <Textarea value={notiz} onChange={(_e, d) => setNotiz(d.value)} />
        </Field>
        {todoEntity ? (
          <>
            <Switch label={t('wartung.reminderLabel')} checked={reminder} onChange={(_e, d) => setReminder(d.checked)} />
            {dueIso ? <div className={styles.muted}>{t('wartung.dueHint', { date: formatDate(dueIso) })}</div> : null}
          </>
        ) : null}
      </div>

      {render.loading ? <LoadingState variant="inline" label={t('wartung.previewLoading')} /> : null}
      {render.data?.preview ? (
        <img className={styles.preview} src={pngSrc(render.data.preview.design_png)} alt={t('wartung.previewAlt')} />
      ) : null}

      <div className={styles.actions}>
        <Button appearance="primary" disabled={!canPrint} aria-busy={printFlow.busy} onClick={() => source && void printFlow.run(source)}>
          {t('wartung.print')}
        </Button>
      </div>

      {todoOk ? (
        <MessageBar intent="success" role="status">
          <MessageBarBody>{t('wartung.reminderCreated')}</MessageBarBody>
        </MessageBar>
      ) : null}
      {todoError ? <ErrorMessage error={todoError} /> : null}
    </div>
  );
}
