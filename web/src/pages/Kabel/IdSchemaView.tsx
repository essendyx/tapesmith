/** Reiter „ID-Schema": TIA-606-Muster oder freie fortlaufende Kabel-IDs. */
import { useEffect, useState } from 'react';
import {
  Button,
  Checkbox,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Switch,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Open20Regular } from '@fluentui/react-icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ErrorMessage } from '../../components/ErrorMessage';
import { generateIds } from './api';

const DEFAULT_PATTERN = '{rack}.U{unit:02}:P{port:02}';

const useStyles = makeStyles({
  col: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  list: {
    maxHeight: '260px',
    overflowY: 'auto',
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    display: 'flex',
    flexDirection: 'column',
    rowGap: '2px',
    margin: 0,
    padding: 0,
    listStyle: 'none',
  },
  dup: { color: tokens.colorPaletteRedForeground1, fontWeight: tokens.fontWeightSemibold },
  toolbar: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
});

export function IdSchemaView(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kabel');
  const navigate = useNavigate();

  const [frei, setFrei] = useState(false);
  const [pattern, setPattern] = useState(DEFAULT_PATTERN);
  const [rack, setRack] = useState('R1');
  const [units, setUnits] = useState('1');
  const [ports, setPorts] = useState('1-24');
  const [count, setCount] = useState('10');
  const [registerIds, setRegisterIds] = useState(false);

  const [ids, setIds] = useState<string[]>([]);
  const [duplicates, setDuplicates] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    if (frei) return;
    let cancelled = false;
    generateIds({ mode: 'schema', pattern, ranges: [{ rack, units, ports }], table: false })
      .then((result) => {
        if (cancelled) return;
        setIds(result.ids);
        setDuplicates(result.duplicates);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setIds([]);
        setError(err);
      });
    return () => {
      cancelled = true;
    };
  }, [frei, pattern, rack, units, ports]);

  async function openSeries(): Promise<void> {
    setOpening(true);
    setError(null);
    try {
      const result = frei
        ? await generateIds({ mode: 'frei', count: Number(count), register: registerIds, table: true })
        : await generateIds({ mode: 'schema', pattern, ranges: [{ rack, units, ports }], register: registerIds, table: true });
      if (result.pending_id) navigate(`/vorlagen?vorlage=kabelfahne&import=${result.pending_id}`);
    } catch (err) {
      setError(err);
    } finally {
      setOpening(false);
    }
  }

  return (
    <div className={styles.col}>
      <Switch label={t('schema.freeSwitch')} checked={frei} onChange={(_e, d) => setFrei(d.checked)} />

      {frei ? (
        <Field label={t('schema.countLabel')}>
          <Input value={count} onChange={(_e, d) => setCount(d.value)} inputMode="numeric" />
        </Field>
      ) : (
        <div className={styles.grid}>
          <Field label={t('schema.patternLabel')}>
            <Input value={pattern} onChange={(_e, d) => setPattern(d.value)} />
          </Field>
          <Field label={t('schema.rackLabel')}>
            <Input value={rack} onChange={(_e, d) => setRack(d.value)} />
          </Field>
          <Field label={t('schema.unitsLabel')} hint={t('schema.unitsHint')}>
            <Input value={units} onChange={(_e, d) => setUnits(d.value)} />
          </Field>
          <Field label={t('schema.portsLabel')} hint={t('schema.portsHint')}>
            <Input value={ports} onChange={(_e, d) => setPorts(d.value)} />
          </Field>
        </div>
      )}

      <Checkbox label={t('common.registerCheckbox')} checked={registerIds} onChange={(_e, d) => setRegisterIds(d.checked === true)} />

      {error ? <ErrorMessage error={error} /> : null}

      {!frei ? (
        <>
          {duplicates.length ? (
            <MessageBar intent="warning" data-testid="ids-duplicates">
              <MessageBarBody>
                <MessageBarTitle>{t('common.duplicatesTitle')}</MessageBarTitle>
                {duplicates.join(', ')}
              </MessageBarBody>
            </MessageBar>
          ) : null}
          <ul className={styles.list} aria-label={t('schema.idsListAriaLabel')} data-testid="ids-list">
            {ids.map((id) => (
              <li key={id} className={duplicates.includes(id) ? styles.dup : undefined}>
                {id}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <div className={styles.toolbar}>
        <Button appearance="primary" icon={<Open20Regular />} disabled={opening} aria-busy={opening} onClick={() => void openSeries()}>
          {opening ? t('common.opening') : t('common.openSeries')}
        </Button>
      </div>
    </div>
  );
}
