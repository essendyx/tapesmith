/** Wert in die Zwischenablage kopieren und mit einer kurzen Meldung bestätigen. */
import { useTranslation } from 'react-i18next';
import { useNotify } from '../../components/NotifyProvider';

export function useCopy(): (value: string, label: string) => Promise<void> {
  const { t } = useTranslation('zugriff');
  const notify = useNotify();
  return async (value, label) => {
    try {
      await navigator.clipboard.writeText(value);
      notify({ intent: 'success', title: t('newToken.copied', { label }) });
    } catch {
      notify({ intent: 'error', title: t('newToken.copyFailed') });
    }
  };
}
