/** Angaben zum Druckdienst (Version, Laufzeit, PID, Port, Ordner, Log) für die Karte „Hilfe und Diagnose“. */
import { Body1, Button } from '@fluentui/react-components';
import { FolderOpen20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { isAppWindow, openPath } from '../../../platform';
import { useDaemon } from '../api';
import { formatUptime } from '../format';
import { FieldRow, ValueText } from '../../../components/FieldRow';

/** Zeilen für eine `FieldRows`-Liste; ohne Angaben ein kurzer Hinweis. */
export function DaemonInfoRows(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const daemon = useDaemon();
  const d = daemon.data;
  if (!d) return <Body1>{t('daemon.empty')}</Body1>;
  return (
    <>
      <FieldRow label={t('daemon.version')} control={<ValueText>{d.version}</ValueText>} />
      <FieldRow label={t('daemon.uptime')} control={<ValueText>{formatUptime(d.uptime_s)}</ValueText>} />
      <FieldRow label={t('daemon.pid')} control={<ValueText>{d.pid}</ValueText>} />
      <FieldRow label={t('daemon.webPort')} control={<ValueText>{d.web_port}</ValueText>} />
      <FieldRow label={t('daemon.appDir')} help={d.app_dir} />
      <FieldRow
        label={t('daemon.logPath')}
        help={d.log_path}
        control={
          isAppWindow() ? (
            <Button appearance="secondary" icon={<FolderOpen20Regular />} onClick={() => void openPath(d.log_path)}>
              {t('daemon.openLog')}
            </Button>
          ) : undefined
        }
      />
    </>
  );
}
