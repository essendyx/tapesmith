/**
 * Karte „Hilfe und Diagnose“: Angaben zum Druckdienst (Version, Laufzeit, PID, Pfade) und „Problem
 * melden“, das ein Zip mit Version, Status und Logs lädt.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Spinner } from '@fluentui/react-components';
import { ArrowDownload20Regular } from '@fluentui/react-icons';
import { Section } from '../../../components/Section';
import { ErrorMessage } from '../../../components/ErrorMessage';
import { useNotify } from '../../../components/NotifyProvider';
import { apiDownload } from '../../../api/client';
import { FieldRows } from '../../../components/FieldRow';
import { DaemonInfoRows } from './DaemonCard';
import { SUPPORT_CARD_ID } from '../sectionIds';

export function SupportCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const onReport = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiDownload('/api/v1/support/report', {}, 'tapesmith-bericht.zip', 'POST');
      notify({ intent: 'success', title: t('support.success') });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div id={SUPPORT_CARD_ID}>
      <Section
        title={t('support.title')}
        description={t('support.description')}
        actions={
          <Button
            appearance="secondary"
            icon={busy ? <Spinner size="tiny" /> : <ArrowDownload20Regular />}
            disabled={busy}
            aria-busy={busy || undefined}
            onClick={() => void onReport()}
          >
            {t('support.action')}
          </Button>
        }
      >
        {error ? <ErrorMessage error={error} title={t('support.failed')} /> : null}
        <FieldRows>
          <DaemonInfoRows />
        </FieldRows>
      </Section>
    </div>
  );
}
