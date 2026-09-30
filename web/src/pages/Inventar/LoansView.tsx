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
  ToggleButton,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Add20Regular, ArrowUndo20Regular, ErrorCircle16Filled, Tag20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { errorText } from './errors';
import { DataList, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { ListToolbar } from '../../components/ListToolbar';
import { RowActions } from '../../components/RowActions';
import { useNotify } from '../../components/NotifyProvider';
import { useFormat } from '../../i18n/format';
import type { InventoryLabelRequest, LoanJson } from '../../api/types';
import { createLoan, fetchLoans, returnLoan } from './api';
import { LabelDialog } from './LabelDialog';

const useStyles = makeStyles({
  toolbar: { display: 'flex', justifyContent: 'space-between', marginBottom: tokens.spacingVerticalM, flexWrap: 'wrap', gap: tokens.spacingHorizontalS },
  switcher: { display: 'flex', columnGap: tokens.spacingHorizontalXS },
  formRow: { display: 'flex', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXS, flexWrap: 'wrap' },
});


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
    <RowActions
      title={loan.item}
      primary={
        loan.open ? (
          <Button
            icon={<ArrowUndo20Regular />}
            aria-label={t('loans.for', { action: t('loans.returned'), item: loan.item })}
            onClick={() => void onReturn(loan)}
          >
            {t('loans.returned')}
          </Button>
        ) : undefined
      }
      actions={[{ key: 'label', label: t('loans.label'), icon: <Tag20Regular />, onClick: () => setLabelLoanId(loan.id) }]}
    />
  );

  const columns: ListColumn<LoanJson>[] = [
    { id: 'item', header: t('loans.table.item'), kind: 'title', cell: (loan) => loan.item },
    { id: 'person', header: t('loans.table.person'), cell: (loan) => loan.person },
    { id: 'since', header: t('loans.table.since'), cell: (loan) => fmtDate(loan.since) },
    { id: 'due', header: t('loans.table.due'), cell: (loan) => fmtDate(loan.due) },
    { id: 'status', header: t('loans.table.status'), kind: 'status', cell: (loan) => statusBadge(loan) },
    { id: 'actions', header: t('loans.table.actions'), kind: 'actions', cell: (loan) => actions(loan) },
  ];

  const labelRequest: InventoryLabelRequest | null = labelLoanId !== null ? { type: 'loan', loan_id: labelLoanId } : null;

  return (
    <div>
      <ListToolbar
        actions={
          <Button appearance="primary" icon={<Add20Regular />} onClick={() => setLendOpen(true)}>
            {t('loans.lend')}
          </Button>
        }
      >
        <div className={styles.switcher} role="group" aria-label={t('loans.a11y.view')}>
          <ToggleButton checked={openOnly} onClick={() => setOpenOnly(true)}>
            {t('loans.open')}
          </ToggleButton>
          <ToggleButton checked={!openOnly} onClick={() => setOpenOnly(false)}>
            {t('loans.all')}
          </ToggleButton>
        </div>
      </ListToolbar>

      <DataList
        items={loans}
        columns={columns}
        getKey={(loan) => loan.id}
        label={t('loans.a11y.list')}
        loading={!loaded}
        empty={<EmptyState title={t('loans.empty.title')} body={t('loans.empty.body')} />}
      />

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
