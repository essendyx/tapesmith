/** Tab ASN-Serien: Paperless-Stand, Scan-Test-Hinweis, Reservieren, Verwerfen. */
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Table,
  TableBody,
  TableCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Trans, useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { exportLabel } from '../../api/labels';
import { Section } from '../../components/Section';
import { ErrorMessage, useErrorText } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { useNotify } from '../../components/NotifyProvider';
import { useLayoutStyles } from '../../theme/layout';
import { reserveAsn, useAsnNext, voidAsn } from './api';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

const useStyles = makeStyles({
  countField: { width: '140px' },
  muted: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
});

export function AsnView(): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('paperless');
  const { t: tc } = useTranslation('common');
  const navigate = useNavigate();
  const notify = useNotify();
  const errorText = useErrorText();
  const next = useAsnNext();

  const [count, setCount] = useState('1');
  const [reserving, setReserving] = useState(false);
  const [reserved, setReserved] = useState<string[]>([]);
  const [voidTarget, setVoidTarget] = useState<string | null>(null);
  const [voidReason, setVoidReason] = useState('');
  const [exporting, setExporting] = useState(false);

  useDialogFocusReturn(voidTarget !== null);

  async function onExportTest(): Promise<void> {
    if (!next.data) return;
    setExporting(true);
    try {
      await exportLabel({ kind: 'template', template: 'asn', values: { asn: next.data.next } }, {}, 'png');
    } catch (err) {
      const e = errorText(err);
      notify({ intent: 'error', title: t('asn.exportFailedTitle'), body: e.message || undefined });
    } finally {
      setExporting(false);
    }
  }

  async function onReserve(): Promise<void> {
    const n = Number(count);
    if (!Number.isInteger(n) || n < 1) return;
    setReserving(true);
    try {
      const result = await reserveAsn(n);
      setReserved((prev) => [...result.numbers, ...prev]);
      navigate(`/vorlagen?vorlage=asn&import=${result.pending_id}`);
    } catch (err) {
      const e = errorText(err);
      notify({ intent: 'error', title: t('asn.reserveFailedTitle'), body: [e.message, e.hint].filter(Boolean).join(' ') || undefined });
    } finally {
      setReserving(false);
    }
  }

  async function onVoidConfirm(): Promise<void> {
    if (!voidTarget || !voidReason.trim()) return;
    try {
      await voidAsn(voidTarget, voidReason.trim());
      setReserved((prev) => prev.filter((n) => n !== voidTarget));
      notify({ intent: 'success', title: t('asn.discardedTitle', { asn: voidTarget }) });
    } catch (err) {
      const e = errorText(err);
      notify({ intent: 'error', title: t('asn.discardFailedTitle'), body: e.message || undefined });
    } finally {
      setVoidTarget(null);
      setVoidReason('');
    }
  }

  return (
    <div className={layout.stack}>
      <Section title={t('asn.nextTitle')}>
        {next.isLoading ? <LoadingState variant="inline" /> : null}
        {next.error ? <ErrorMessage error={next.error} title={t('asn.notReachable')} /> : null}
        {next.data ? (
          <>
            <p>
              <Trans
                i18nKey="paperless:asn.info"
                values={{ paperlessNext: next.data.paperless_next, localNext: next.data.local_next ?? t('asn.noLocal'), next: next.data.next }}
                components={{ strong: <strong /> }}
              />
            </p>
            <MessageBar intent="warning">
              <MessageBarBody>{next.data.hint}</MessageBarBody>
            </MessageBar>
            <Button onClick={() => void onExportTest()} disabled={exporting}>
              {t('asn.exportTest')}
            </Button>
          </>
        ) : null}
      </Section>

      <Section title={t('asn.reserveTitle')}>
        <div className={layout.rowWrap}>
          <Field label={t('asn.count')} className={styles.countField}>
            <Input type="number" min={1} max={500} value={count} onChange={(_e, data) => setCount(data.value)} />
          </Field>
          <Button appearance="primary" onClick={() => void onReserve()} disabled={reserving}>
            {t('asn.reserveSubmit')}
          </Button>
        </div>
      </Section>

      {reserved.length ? (
        <Section title={t('asn.recentTitle')}>
          <Table size="small" aria-label={t('asn.recentAriaLabel')}>
            <TableBody>
              {reserved.map((number) => (
                <TableRow key={number}>
                  <TableCell>{number}</TableCell>
                  <TableCell>
                    <Button appearance="subtle" onClick={() => setVoidTarget(number)}>
                      {t('asn.discard')}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      ) : null}

      <Dialog open={voidTarget !== null} onOpenChange={(_e, data) => !data.open && setVoidTarget(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('asn.voidDialog.title')}</DialogTitle>
            <DialogContent>
              <Field label={t('asn.voidDialog.reason')} required>
                <Input value={voidReason} onChange={(_e, data) => setVoidReason(data.value)} autoFocus />
              </Field>
              <p className={styles.muted}>{voidTarget}</p>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setVoidTarget(null)}>
                {tc('actions.cancel')}
              </Button>
              <Button appearance="primary" onClick={() => void onVoidConfirm()} disabled={!voidReason.trim()}>
                {t('asn.discard')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
