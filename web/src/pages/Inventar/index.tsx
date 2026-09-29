/** Seite „Inventar": Boxen, Suche, Verleih, Reiter über `?tab=`. */
import { Tab, TabList, makeStyles } from '@fluentui/react-components';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { space } from '../../theme/layout';
import { BoxesView } from './BoxesView';
import { SearchView } from './SearchView';
import { LoansView } from './LoansView';

type TabKey = 'boxen' | 'suche' | 'verleih';

function currentTab(value: string | null): TabKey {
  return value === 'suche' || value === 'verleih' ? value : 'boxen';
}

const useStyles = makeStyles({ content: { marginTop: space.section } });

export default function InventarPage(): JSX.Element {
  const { t } = useTranslation('inventar');
  const styles = useStyles();
  const [params, setParams] = useSearchParams();
  const tab = currentTab(params.get('tab'));
  const boxId = params.get('box');

  const setTab = (next: TabKey) => {
    const p = new URLSearchParams(params);
    p.set('tab', next);
    if (next !== 'boxen') p.delete('box');
    setParams(p, { replace: true });
  };

  const openBox = (id: string) => {
    const p = new URLSearchParams(params);
    p.set('tab', 'boxen');
    p.set('box', id);
    setParams(p);
  };

  const clearBoxParam = () => {
    if (!boxId) return;
    const p = new URLSearchParams(params);
    p.delete('box');
    setParams(p, { replace: true });
  };

  return (
    <>
      <PageHeader title={moduleTexts('inventar').name} subtitle={moduleTexts('inventar').description} />
      <TabList selectedValue={tab} onTabSelect={(_e, data) => setTab(data.value as TabKey)}>
        <Tab value="boxen">{t('tabs.boxes')}</Tab>
        <Tab value="suche">{t('tabs.search')}</Tab>
        <Tab value="verleih">{t('tabs.loans')}</Tab>
      </TabList>
      <div className={styles.content}>
        {tab === 'boxen' ? <BoxesView boxIdFromUrl={boxId} onBoxHandled={clearBoxParam} /> : null}
        {tab === 'suche' ? <SearchView onOpenBox={openBox} /> : null}
        {tab === 'verleih' ? <LoansView /> : null}
      </div>
    </>
  );
}
