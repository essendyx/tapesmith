/** Seite Paperless: ASN-Serien und Garantie-Etikett. */
import { useState } from 'react';
import { Tab, TabList } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { useLayoutStyles } from '../../theme/layout';
import { AsnView } from './AsnView';
import { GarantieView } from './GarantieView';

type TabKey = 'asn' | 'garantie';

export default function PaperlessPage(): JSX.Element {
  const layout = useLayoutStyles();
  const { t } = useTranslation('paperless');
  const [tab, setTab] = useState<TabKey>('asn');

  return (
    <div className={layout.stack}>
      <PageHeader title={moduleTexts('paperless').name} subtitle={moduleTexts('paperless').description} />
      <TabList selectedValue={tab} onTabSelect={(_e, data) => setTab(data.value as TabKey)}>
        <Tab value="asn">{t('tabs.asn')}</Tab>
        <Tab value="garantie">{t('tabs.garantie')}</Tab>
      </TabList>
      {tab === 'asn' ? <AsnView /> : <GarantieView />}
    </div>
  );
}
