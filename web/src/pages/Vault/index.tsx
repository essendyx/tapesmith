/** Seite Obsidian-Vault: Notizen als Datenquelle, Vermerk nach dem Druck, Snippet. */
import { useState } from 'react';
import { Tab, TabList } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { useLayoutStyles } from '../../theme/layout';
import { NotesView } from './NotesView';
import { SnippetView } from './SnippetView';

type VaultTab = 'notizen' | 'snippet';

export default function VaultPage(): JSX.Element {
  const layout = useLayoutStyles();
  const { t } = useTranslation('vault');
  const [tab, setTab] = useState<VaultTab>('notizen');
  return (
    <div className={layout.stack}>
      <PageHeader title={moduleTexts('vault').name} subtitle={moduleTexts('vault').description} />
      <Section flush>
        <TabList selectedValue={tab} onTabSelect={(_e, d) => setTab(d.value as VaultTab)}>
          <Tab value="notizen">{t('tabs.notes')}</Tab>
          <Tab value="snippet">{t('tabs.snippet')}</Tab>
        </TabList>
      </Section>
      {tab === 'notizen' ? <NotesView /> : <SnippetView />}
    </div>
  );
}
