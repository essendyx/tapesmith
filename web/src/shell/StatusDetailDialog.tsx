/** Druckerstatus im Detail: Werte als zweispaltige Liste, Knopf „Status abfragen“. */
import { Fragment, useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowSync20Regular } from '@fluentui/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { qk, refreshStatus, useStatus } from '../api/core';
import { BluetoothSettingsButton } from '../components/BluetoothSettingsButton';
import { ErrorMessage } from '../components/ErrorMessage';
import { formatDateTime } from '../i18n/format';
import { StatusDot } from './StatusDot';

const useStyles = makeStyles({
  surface: { maxWidth: '620px', borderRadius: tokens.borderRadiusXLarge },
  head: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
  list: {
    display: 'grid',
    gridTemplateColumns: 'minmax(8em, max-content) minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
    padding: tokens.spacingHorizontalL,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase300,
    maxHeight: '50vh',
    overflowY: 'auto',
  },
  term: { color: tokens.colorNeutralForeground3 },
  value: {
    margin: 0,
    color: tokens.colorNeutralForeground1,
    fontFamily: tokens.fontFamilyMonospace,
    overflowWrap: 'anywhere',
    whiteSpace: 'pre-wrap',
  },
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  checked: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
});

/** Zerlegt „Name: Wert“-Zeilen des Servers in Paare; Zeilen ohne Doppelpunkt bleiben ohne Namen. */
export function detailPairs(detail: string): { term: string; value: string }[] {
  return detail
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line) => {
      const i = line.indexOf(': ');
      return i > 0 ? { term: line.slice(0, i), value: line.slice(i + 2) } : { term: '', value: line };
    });
}

export function StatusDetailDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const status = useStatus();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const view = status.data?.view;
  const checkedAt = status.data?.report.checked_at;

  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      const fresh = await refreshStatus();
      queryClient.setQueryData(qk.status, fresh);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => props.onOpenChange(d.open)}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>
            <span className={styles.head}>
              {view ? <StatusDot role={view.role} /> : null}
              {view?.title ?? t('status.dialogTitle')}
            </span>
          </DialogTitle>
          <DialogContent className={styles.content}>
            {view ? (
              <dl className={styles.list} data-testid="status-detail" aria-label={t('status.detailLabel')}>
                {detailPairs(view.detail).map((p, i) => (
                  <Fragment key={`${p.term}-${i}`}>
                    <dt className={styles.term}>{p.term}</dt>
                    <dd className={styles.value}>{p.value}</dd>
                  </Fragment>
                ))}
              </dl>
            ) : (
              <Spinner size="small" label={t('status.loadingDetail')} />
            )}
            {checkedAt ? <span className={styles.checked}>{t('status.checked', { time: formatDateTime(checkedAt) })}</span> : null}
            {error ? <ErrorMessage error={error} /> : null}
          </DialogContent>
          <DialogActions>
            <BluetoothSettingsButton onError={setError} />
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : <ArrowSync20Regular />}
              disabled={busy}
              aria-busy={busy}
              onClick={() => void refresh()}
            >
              {t('status.refresh')}
            </Button>
            <Button appearance="secondary" onClick={() => props.onOpenChange(false)}>
              {t('common:actions.close')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
