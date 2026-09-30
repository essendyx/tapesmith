/**
 * Einmalige Rückfrage nach der automatischen Update-Prüfung. Ohne Zustimmung baut Tapesmith von sich
 * aus keine Verbindung ins Internet auf (Datenschutzzusage in CODE_SIGNING_POLICY.md).
 * Der Dienst meldet `consent_needed`, solange die installierte App noch nie gefragt hat und die Prüfung
 * aus ist. Beide Antworten speichert `POST /update/consent`; danach erscheint der Hinweis nicht mehr.
 * Fehler beim Laden bleiben still (z. B. ohne Adminrechte), Fehler beim Speichern stehen im Hinweis.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowSync20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { UPDATE_QUERY_KEY, answerUpdateConsent, useUpdateStatus } from '../api/update';
import { motion } from '../theme/motion';

const useStyles = makeStyles({
  root: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalXL} 0`,
    ...motion.slideUp,
  },
  error: { display: 'block', marginTop: tokens.spacingVerticalXS, color: tokens.colorPaletteRedForeground1 },
});

export function UpdateConsentBanner(): JSX.Element | null {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const queryClient = useQueryClient();
  const status = useUpdateStatus();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!status.data?.consent_needed) return null;

  const answer = (enabled: boolean) => {
    setBusy(true);
    setFailed(false);
    answerUpdateConsent(enabled).then(
      (next) => {
        queryClient.setQueryData(UPDATE_QUERY_KEY, next);
        setBusy(false);
      },
      () => {
        setFailed(true);
        setBusy(false);
      },
    );
  };

  return (
    <div className={styles.root}>
      <MessageBar intent="info" layout="multiline" icon={<ArrowSync20Regular />} data-testid="update-consent">
        <MessageBarBody>
          <MessageBarTitle>{t('updateConsent.title')}</MessageBarTitle>
          {t('updateConsent.body')}
          {failed ? (
            <span role="alert" className={styles.error}>
              {t('updateConsent.error')}
            </span>
          ) : null}
        </MessageBarBody>
        <MessageBarActions>
          <Button appearance="primary" size="small" disabled={busy} onClick={() => answer(true)}>
            {t('updateConsent.enable')}
          </Button>
          <Button appearance="secondary" size="small" disabled={busy} onClick={() => answer(false)}>
            {t('updateConsent.disable')}
          </Button>
        </MessageBarActions>
      </MessageBar>
    </div>
  );
}
