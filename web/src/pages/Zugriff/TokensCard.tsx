/** Karte „API-Tokens“: Tabelle, Widerrufen mit Rückfrage, Dialog „Neues Token“. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Body1,
  Button,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Add20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { ApiError } from '../../api/client';
import { absoluteTime, relativeTime } from '../Verlauf/time';
import { ACCESS_KEY, revokeAccessToken } from './api';
import { NewTokenDialog } from './NewTokenDialog';
import type { TokenInfoJson } from './types';
import { TableScroll } from '../../components/TableScroll';

const useStyles = makeStyles({
  empty: { color: tokens.colorNeutralForeground3 },
  // Mindestbreite: auf dem Handy und bei 200 % scrollt die Tabelle, statt Spalten zu überlagern.
  table: { minWidth: '640px' },
});

export function TokensCard(props: { tokens: TokenInfoJson[] }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const confirm = useConfirm();
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const onRevoke = async (tok: TokenInfoJson) => {
    const ok = await confirm({
      title: t('tokens.revokeConfirmTitle', { name: tok.name }),
      message: t('tokens.revokeConfirmMessage'),
      confirmText: t('tokens.revoke'),
      danger: true,
    });
    if (!ok) return;
    setRevoking(tok.id);
    try {
      await revokeAccessToken(tok.id);
      void queryClient.invalidateQueries({ queryKey: ACCESS_KEY });
      notify({ intent: 'success', title: t('tokens.revokeSuccess', { name: tok.name }) });
    } catch (err) {
      notify({
        intent: 'error',
        title: t('tokens.revokeErrorTitle'),
        body: err instanceof ApiError || err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRevoking(null);
    }
  };

  return (
    <Section
      id="tokens"
      title={t('tokens.title')}
      actions={
        <Button appearance="primary" icon={<Add20Regular />} onClick={() => setDialogOpen(true)}>
          {t('tokens.new')}
        </Button>
      }
    >
      {props.tokens.length === 0 ? (
        <Body1 className={styles.empty}>{t('tokens.empty')}</Body1>
      ) : (
        <TableScroll label={t('tokens.table.scrollAria')}>
        <Table aria-label={t('tokens.table.ariaLabel')} className={styles.table}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t('tokens.table.name')}</TableHeaderCell>
              <TableHeaderCell>{t('tokens.table.role')}</TableHeaderCell>
              <TableHeaderCell>{t('tokens.table.created')}</TableHeaderCell>
              <TableHeaderCell>{t('tokens.table.lastUsed')}</TableHeaderCell>
              <TableHeaderCell>{t('tokens.table.hint')}</TableHeaderCell>
              <TableHeaderCell>
                <span className="p12-visually-hidden">{t('tokens.table.actions')}</span>
              </TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {props.tokens.map((tok) => (
              <TableRow key={tok.id}>
                <TableCell>{tok.name}</TableCell>
                <TableCell>{tok.role_label}</TableCell>
                <TableCell>{absoluteTime(tok.created)}</TableCell>
                <TableCell>{tok.last_used ? relativeTime(tok.last_used) : t('tokens.table.never')}</TableCell>
                <TableCell>{tok.hint}</TableCell>
                <TableCell>
                  <Button
                    appearance="subtle"
                    icon={<Delete20Regular />}
                    disabled={revoking === tok.id}
                    onClick={() => void onRevoke(tok)}
                  >
                    {t('tokens.revoke')}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </TableScroll>
      )}
      <NewTokenDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </Section>
  );
}
