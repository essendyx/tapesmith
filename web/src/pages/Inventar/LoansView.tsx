/** Reiter „Verleih": offene/alle Posten, Verleihen, Rückgabe, überfällig-Badge, Verleih-Label. */
import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  ToggleButton,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ErrorCircle16Filled } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { errorText } from './errors';
import { EmptyState } from '../../components/EmptyState';
import { useMediaQuery } from '../../components/useMediaQuery';
import { useNotify } from '../../components/NotifyProvider';
import { useFormat } from '../../i18n/format';
import type { InventoryLabelRequest, LoanJson } from '../../api/types';
import { createLoan, fetchLoans, returnLoan } from './api';
import { LabelDialog } from './LabelDialog';

const useStyles = makeStyles({
  toolbar: { display: 'flex', justifyContent: 'space-between', marginBottom: tokens.spacingVerticalM, flexWrap: 'wrap', gap: tokens.spacingHorizontalS },
  switcher: { display: 'flex', columnGap: tokens.spacingHorizontalXS },
  formRow: { display: 'flex', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXS, flexWrap: 'wrap' },
  /** Eigener Scroll-Container: eine breite Tabelle scrollt hier seitlich, nie die ganze Seite. */
  tableScroll: { overflowX: 'auto', maxWidth: '100%' },
  cards: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  card: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
    minWidth: 0,
  },
  cardHead: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  cardTitle: { fontWeight: tokens.fontWeightSemibold, overflowWrap: 'anywhere', minWidth: 0 },
  cardMeta: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200, overflowWrap: 'anywhere' },
});

/** Ab dieser Breite werden die Posten als Karten statt als Tabelle gezeigt (responsiv bis 360 px). */
const NARROW_QUERY = '(max-width: 639px)';

export function LoansView(): JSX.Element {
  const { t } = useTranslation('inventar');
  const { formatDate } = useFormat();
  const fmtDate = (iso: string | null): string => {
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : formatDate(d);
  };
  const styles = useStyles();
  const notify = useNotify();
  const narrow = useMediaQuery(NARROW_QUERY);
  const [openOnly, setOpenOnly] = useState(true);
  const [loans, setLoans] = useState<LoanJson[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [lendOpen, setLendOpen] = useState(false);
  const [item, setItem] = useState('');
  const [person, setPerson] = useState('');
  const [due, setDue] = useState('');
  const [labelLoanId, setLabelLoanId] = useState<number | null>(null);

  const load = () => {
    fetchLoans(openOnly)
      .then((r) => {
        setLoans(r.loans);
        setLoaded(true);
      })
      .catch((err: unknown) => notify({ intent: 'error', ...errorText(err) }));
  };

  useEffect(load, [openOnly, notify]);

  const submitLend = async () => {
    if (!item.trim() || !person.trim()) return;
    try {
      await createLoan({ item, person, due: due || undefined });
      setItem('');
      setPerson('');
      setDue('');
      setLendOpen(false);
      load();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const onReturn = async (loan: LoanJson) => {
    try {
      await returnLoan(loan.id);
      load();
    } catch (err) {
      notify({ intent: 'error', ...errorText(err) });
    }
  };

  const statusBadge = (loan: LoanJson) =>
    loan.overdue ? (
      <Badge appearance="filled" color="danger" icon={<ErrorCircle16Filled />}>
        {t('loans.status.overdue')}
      </Badge>
    ) : loan.open ? (
      <Badge appearance="outline" color="informative">
        {t('loans.status.lent')}
      </Badge>
    ) : (
      <Badge appearance="outline" color="success">
        {t('loans.status.returned')}
      </Badge>
    );

  const actions = (loan: LoanJson) => (
    <div className={styles.formRow}>
      {loan.open ? (
        <Button size="small" onClick={() => void onReturn(loan)}>
          {t('loans.returned')}
        </Button>
      ) : null}
      <Button size="small" onClick={() => setLabelLoanId(loan.id)}>
        {t('loans.label')}
      </Button>
    </div>
  );

  const labelRequest: InventoryLabelRequest | null = labelLoanId !== null ? { type: 'loan', loan_id: labelLoanId } : null;

  return (
    <div>
      <div className={styles.toolbar}>
        <div className={styles.switcher} role="group" aria-label={t('loans.a11y.view')}>
          <ToggleButton checked={openOnly} onClick={() => setOpenOnly(true)}>
            {t('loans.open')}
          </ToggleButton>
          <ToggleButton checked={!openOnly} onClick={() => setOpenOnly(false)}>
            {t('loans.all')}
          </ToggleButton>
        </div>
        <Button appearance="primary" onClick={() => setLendOpen(true)}>
          {t('loans.lend')}
        </Button>
      </div>

      {loaded && loans.length === 0 ? (
        <EmptyState title={t('loans.empty.title')} body={t('loans.empty.body')} />
      ) : narrow ? (
        <ul className={styles.cards} aria-label={t('loans.a11y.list')}>
          {loans.map((loan) => (
            <li key={loan.id} className={styles.card}>
              <div className={styles.cardHead}>
                <span className={styles.cardTitle}>{loan.item}</span>
                {statusBadge(loan)}
              </div>
              <span className={styles.cardMeta}>{loan.person}</span>
              <span className={styles.cardMeta}>
                {loan.due
                  ? t('loans.sinceDue', { date: fmtDate(loan.since), due: fmtDate(loan.due) })
                  : t('loans.since', { date: fmtDate(loan.since) })}
              </span>
              {actions(loan)}
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.tableScroll}>
          <Table aria-label={t('loans.a11y.list')}>
            <TableHeader>
              <TableRow>
                <TableHeaderCell>{t('loans.table.item')}</TableHeaderCell>
                <TableHeaderCell>{t('loans.table.person')}</TableHeaderCell>
                <TableHeaderCell>{t('loans.table.since')}</TableHeaderCell>
                <TableHeaderCell>{t('loans.table.due')}</TableHeaderCell>
                <TableHeaderCell>{t('loans.table.status')}</TableHeaderCell>
                <TableHeaderCell>{t('loans.table.actions')}</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loans.map((loan) => (
                <TableRow key={loan.id}>
                  <TableCell>{loan.item}</TableCell>
                  <TableCell>{loan.person}</TableCell>
                  <TableCell>{fmtDate(loan.since)}</TableCell>
                  <TableCell>{fmtDate(loan.due)}</TableCell>
                  <TableCell>{statusBadge(loan)}</TableCell>
                  <TableCell>{actions(loan)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={lendOpen} onOpenChange={(_e, data) => !data.open && setLendOpen(false)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('loans.lend')}</DialogTitle>
            <DialogContent>
              <div className={styles.formRow}>
                <Field label={t('loans.item')}>
                  <Input value={item} onChange={(_e, d) => setItem(d.value)} />
                </Field>
                <Field label={t('loans.person')}>
                  <Input value={person} onChange={(_e, d) => setPerson(d.value)} />
                </Field>
                <Field label={t('loans.due')}>
                  <Input type="date" value={due} onChange={(_e, d) => setDue(d.value)} />
                </Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!item.trim() || !person.trim()} onClick={() => void submitLend()}>
                {t('loans.lend')}
              </Button>
              <Button appearance="secondary" onClick={() => setLendOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <LabelDialog open={labelLoanId !== null} title={t('loans.label')} request={labelRequest} onClose={() => setLabelLoanId(null)} />
    </div>
  );
}
