/** Seite „Zugriff“: Tokens, LAN, Familie, MCP, Hotfolder, MQTT, Telegram, Zusatzdienste. */
import { LockClosed48Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../components/PageHeader';
import { EmptyState } from '../../components/EmptyState';
import { LoadingState } from '../../components/LoadingState';
import { ApiError } from '../../api/client';
import { useLayoutStyles } from '../../theme/layout';
import { useAccess } from './api';
import { TokensCard } from './TokensCard';
import { LanCard } from './LanCard';
import { FamilyCard } from './FamilyCard';
import { McpCard } from './McpCard';
import { HotfolderCard } from './HotfolderCard';
import { MqttCard } from './MqttCard';
import { TelegramCard } from './TelegramCard';
import { AddonsCard } from './AddonsCard';

export default function ZugriffPage(): JSX.Element {
  const layout = useLayoutStyles();
  const { t } = useTranslation('zugriff');
  const access = useAccess();

  const forbidden = access.error instanceof ApiError && access.error.status === 403;

  return (
    <>
      <PageHeader title={t('page.title')} subtitle={t('page.subtitle')} />
      {forbidden ? (
        <EmptyState icon={<LockClosed48Regular />} title={t('forbidden.title')} body={t('forbidden.body')} />
      ) : (
        <>
          {access.isLoading ? <LoadingState variant="page" /> : null}
          {access.data ? (
            <div className={layout.stack}>
              <TokensCard tokens={access.data.tokens} />
              <LanCard data={access.data} />
              <FamilyCard data={access.data} />
              <McpCard data={access.data} />
              <HotfolderCard data={access.data} />
              <MqttCard data={access.data} />
              <TelegramCard data={access.data} />
              <AddonsCard addons={access.data.addons} />
            </div>
          ) : null}
        </>
      )}
    </>
  );
}
