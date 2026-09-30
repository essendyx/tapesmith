/** Karte „API-Tokens“: Tabelle, Widerrufen mit Rückfrage, Dialog „Neues Token“. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, makeStyles, tokens } from '@fluentui/react-components';
import { Add20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { DataList, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { Section } from '../../components/Section';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { ApiError } from '../../api/client';
import { absoluteTime, relativeTime } from '../Verlauf/time';
import { ACCESS_KEY, revokeAccessToken } from './api';
import { NewTokenDialog } from './NewTokenDialog';
import type { TokenInfoJson } from './types';

const useStyles = makeStyles({
  hint: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200 },
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

  const columns: ListColumn<TokenInfoJson>[] = [
    { id: 'name', header: t('tokens.table.name'), kind: 'title', cell: (tok) => tok.name },
    { id: 'role', header: t('tokens.table.role'), cell: (tok) => tok.role_label },
    { id: 'created', header: t('tokens.table.created'), cell: (tok) => absoluteTime(tok.created) },
    {
      id: 'lastUsed',
      header: t('tokens.table.lastUsed'),
      cell: (tok) => (tok.last_used ? relativeTime(tok.last_used) : t('tokens.table.never')),
    },
    { id: 'hint', header: t('tokens.table.hint'), cell: (tok) => <span className={styles.hint}>{tok.hint}</span> },
    {
      id: 'actions',
      header: t('tokens.table.actions'),
      kind: 'actions',
      cell: (tok) => (
        <Button
          appearance="subtle"
          icon={<Delete20Regular />}
          disabled={revoking === tok.id}
          aria-label={t('tokens.revokeFor', { name: tok.name })}
          onClick={() => void onRevoke(tok)}
        >
          {t('tokens.revoke')}
        </Button>
      ),
    },
  ];

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
      <DataList
        items={props.tokens}
        columns={columns}
        getKey={(tok) => tok.id}
        label={t('tokens.table.ariaLabel')}
        empty={<EmptyState compact title={t('tokens.empty')} />}
      />
      <NewTokenDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </Section>
  );
}
