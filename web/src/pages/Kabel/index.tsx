/** Seite „Kabel": NetBox-Import, ID-Schema und Kabel-Register, Reiter über `?tab=`. */
import { useEffect, useState } from 'react';
import {
  Button,
  Input,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Delete20Regular, Search20Regular } from '@fluentui/react-icons';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { DataList, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { ListToolbar, useToolbarSearchStyles } from '../../components/ListToolbar';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { useConfirm } from '../../components/ConfirmProvider';
import { deleteKabelEntry, fetchKabelRegister } from './api';
import { IdSchemaView } from './IdSchemaView';
import { NetboxView } from './NetboxView';
import type { KabelEntryJson } from './types';
import { dateOnly } from '../Verlauf/time';

type TabKey = 'netbox' | 'schema' | 'register';

function currentTab(value: string | null): TabKey {
  if (value === 'schema' || value === 'register') return value;
  return 'netbox';
}

const useStyles = makeStyles({
  col: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  id: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200 },
  tabs: { marginTop: tokens.spacingVerticalM },
});

function RegisterView(): JSX.Element {
  const styles = useStyles();
  const toolbarStyles = useToolbarSearchStyles();
  const { t } = useTranslation('kabel');
  const confirm = useConfirm();
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<KabelEntryJson[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function load(q: string): void {
    fetchKabelRegister(q)
      .then((result) => {
        setEntries(result.entries);
        setLoaded(true);
        setError(null);
      })
      .catch((err: unknown) => {
        setLoaded(true);
        setError(err);
      });
  }

  useEffect(() => load(''), []);

  async function remove(id: string): Promise<void> {
    const ok = await confirm({ title: t('register.removeConfirmTitle', { id }), danger: true });
    if (!ok) return;
    await deleteKabelEntry(id);
    load(query);
  }

  const columns: ListColumn<KabelEntryJson>[] = [
    { id: 'id', header: t('register.columns.id'), cell: (entry) => <span className={styles.id}>{entry.id}</span> },
    { id: 'source', header: t('register.columns.source'), kind: 'title', cell: (entry) => entry.quelle },
    { id: 'target', header: t('register.columns.target'), cell: (entry) => entry.ziel },
    { id: 'type', header: t('register.columns.type'), cell: (entry) => entry.kabeltyp },
    { id: 'origin', header: t('register.columns.origin'), cell: (entry) => entry.quelle_import },
    { id: 'created', header: t('register.columns.created'), cell: (entry) => (entry.created ? dateOnly(entry.created) : '') },
    {
      id: 'actions',
      header: t('register.columns.actions'),
      kind: 'actions',
      cell: (entry) => (
        <Button
          appearance="subtle"
          icon={<Delete20Regular />}
          aria-label={t('register.removeAria', { id: entry.id })}
          onClick={() => void remove(entry.id)}
        />
      ),
    },
  ];

  return (
    <div>
      <ListToolbar>
        <Input
          className={toolbarStyles.search}
          value={query}
          aria-label={t('register.searchPlaceholder')}
          placeholder={t('register.searchPlaceholder')}
          contentBefore={<Search20Regular />}
          onChange={(_e, d) => setQuery(d.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') load(query);
          }}
        />
        <Button onClick={() => load(query)}>{t('register.search')}</Button>
      </ListToolbar>
      {error && entries.length > 0 ? <ErrorMessage error={error} /> : null}
      <DataList
        items={entries}
        columns={columns}
        getKey={(entry) => entry.id}
        label={t('register.tableAriaLabel')}
        loading={!loaded}
        error={error}
        onRetry={() => load(query)}
        empty={<EmptyState title={t('register.empty.title')} body={t('register.empty.body')} />}
      />
    </div>
  );
}

export default function KabelPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kabel');
  const [params, setParams] = useSearchParams();
  const tab = currentTab(params.get('tab'));

  function setTab(next: TabKey): void {
    const p = new URLSearchParams(params);
    p.set('tab', next);
    setParams(p, { replace: true });
  }

  return (
    <>
      <PageHeader title={moduleTexts('kabel').name} subtitle={moduleTexts('kabel').description} />
      <TabList selectedValue={tab} onTabSelect={(_e, data) => setTab(data.value as TabKey)}>
        <Tab value="netbox">{t('tabs.netbox')}</Tab>
        <Tab value="schema">{t('tabs.schema')}</Tab>
        <Tab value="register">{t('tabs.register')}</Tab>
      </TabList>
      <div className={styles.tabs}>
        <Section>
          {tab === 'netbox' ? <NetboxView /> : null}
          {tab === 'schema' ? <IdSchemaView /> : null}
          {tab === 'register' ? <RegisterView /> : null}
        </Section>
      </div>
    </>
  );
}
