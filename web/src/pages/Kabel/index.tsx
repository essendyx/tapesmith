/** Seite „Kabel": NetBox-Import, ID-Schema und Kabel-Register, Reiter über `?tab=`. */
import { useEffect, useState } from 'react';
import {
  Button,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Delete20Regular, Search20Regular } from '@fluentui/react-icons';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { useConfirm } from '../../components/ConfirmProvider';
import { deleteKabelEntry, fetchKabelRegister } from './api';
import { IdSchemaView } from './IdSchemaView';
import { NetboxView } from './NetboxView';
import type { KabelEntryJson } from './types';

type TabKey = 'netbox' | 'schema' | 'register';

function currentTab(value: string | null): TabKey {
  if (value === 'schema' || value === 'register') return value;
  return 'netbox';
}

const useStyles = makeStyles({
  col: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  toolbar: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  tableWrap: { overflowX: 'auto', maxWidth: '100%' },
  tabs: { marginTop: tokens.spacingVerticalM },
});

function RegisterView(): JSX.Element {
  const styles = useStyles();
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

  return (
    <div className={styles.col}>
      <div className={styles.toolbar}>
        <Input
          value={query}
          placeholder={t('register.searchPlaceholder')}
          contentBefore={<Search20Regular />}
          onChange={(_e, d) => setQuery(d.value)}
        />
        <Button onClick={() => load(query)}>{t('register.search')}</Button>
      </div>
      {error ? <ErrorMessage error={error} /> : null}
      {loaded && entries.length === 0 ? (
        <EmptyState title={t('register.empty.title')} body={t('register.empty.body')} />
      ) : (
        <div className={styles.tableWrap}>
          <Table size="small" aria-label={t('register.tableAriaLabel')}>
            <TableHeader>
              <TableRow>
                <TableHeaderCell>{t('register.columns.id')}</TableHeaderCell>
                <TableHeaderCell>{t('register.columns.source')}</TableHeaderCell>
                <TableHeaderCell>{t('register.columns.target')}</TableHeaderCell>
                <TableHeaderCell>{t('register.columns.type')}</TableHeaderCell>
                <TableHeaderCell>{t('register.columns.origin')}</TableHeaderCell>
                <TableHeaderCell>{t('register.columns.created')}</TableHeaderCell>
                <TableHeaderCell>
                  <span className="p12-visually-hidden">{t('register.columns.actions')}</span>
                </TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell>{entry.id}</TableCell>
                  <TableCell>{entry.quelle}</TableCell>
                  <TableCell>{entry.ziel}</TableCell>
                  <TableCell>{entry.kabeltyp}</TableCell>
                  <TableCell>{entry.quelle_import}</TableCell>
                  <TableCell>{entry.created}</TableCell>
                  <TableCell>
                    <Button
                      appearance="subtle"
                      icon={<Delete20Regular />}
                      aria-label={t('register.removeAria', { id: entry.id })}
                      onClick={() => void remove(entry.id)}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
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
