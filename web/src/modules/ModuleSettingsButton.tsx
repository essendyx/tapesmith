/** Knopf „Zu den Einstellungen“: öffnet die Einstellungskarte eines Moduls (Leerzustände der Modulseiten). */
import { Button } from '@fluentui/react-components';
import { Settings20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

export function ModuleSettingsButton(props: { module: string; appearance?: 'primary' | 'secondary' }): JSX.Element {
  const { t } = useTranslation('modules');
  const navigate = useNavigate();
  return (
    <Button
      appearance={props.appearance ?? 'primary'}
      icon={<Settings20Regular />}
      onClick={() => navigate(`/einstellungen?abschnitt=modul-${props.module}`)}
    >
      {t('settingsLink')}
    </Button>
  );
}
