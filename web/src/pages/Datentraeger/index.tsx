/** Seite „Datenträger" (Modul): Laufwerke, SSH-Disk-Scanner und Plattentausch, Reiter über `?tab=`. */
import { Tab, TabList, makeStyles } from '@fluentui/react-components';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { space } from '../../theme/layout';
import PlattentauschPage from '../Plattentausch';
import { DrivesView } from './DrivesView';
import { SshView } from './SshView';

type TabKey = 'laufwerke' | 'ssh' | 'plattentausch';

function currentTab(value: string | null): TabKey {
  return value === 'ssh' || value === 'plattentausch' ? value : 'laufwerke';
}

const useStyles = makeStyles({ content: { marginTop: space.section } });

export default function DatentraegerPage(): JSX.Element {
  const { t } = useTranslation('datentraeger');
  const styles = useStyles();
  const [params, setParams] = useSearchParams();
  const tab = currentTab(params.get('tab'));

  const setTab = (next: TabKey) => {
    const p = new URLSearchParams(params);
    p.set('tab', next);
    setParams(p, { replace: true });
  };

  return (
    <>
      <PageHeader title={t('title')} subtitle={moduleTexts('datentraeger').description} />
      <TabList selectedValue={tab} onTabSelect={(_e, data) => setTab(data.value as TabKey)}>
        <Tab value="laufwerke">{t('tabs.drives')}</Tab>
        <Tab value="ssh">{t('tabs.ssh')}</Tab>
        <Tab value="plattentausch">{t('tabs.replace')}</Tab>
      </TabList>
      <div className={styles.content}>
        {tab === 'laufwerke' ? <DrivesView /> : null}
        {tab === 'ssh' ? <SshView /> : null}
        {tab === 'plattentausch' ? <PlattentauschPage embedded /> : null}
      </div>
    </>
  );
}
