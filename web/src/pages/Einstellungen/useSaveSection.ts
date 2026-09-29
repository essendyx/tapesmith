/** Speichern eines Einstellungsabschnitts mit Erfolgsmeldung (gemeinsam für generische und eigene Karten). */
import { useTranslation } from 'react-i18next';
import { useNotify } from '../../components/NotifyProvider';
import { translateOr } from '../../i18n';
import { useSettingsEdit } from './context';
import type { SettingsSection } from '../../api/types';

/**
 * Liefert eine Funktion, die die Felder `section` speichert und bei Erfolg „<Titel>: gespeichert“
 * meldet, mit dem Hinweis „Neustart nötig“, sobald ein geändertes Feld `restart` trägt.
 */
export function useSaveSection(): (section: SettingsSection, title?: string) => Promise<boolean> {
  const edit = useSettingsEdit();
  const notify = useNotify();
  const { t } = useTranslation('einstellungen');
  return async (section, title) => {
    const keys = section.fields.map((f) => f.key);
    const restartNeeded = section.fields.some((f) => f.restart && edit.isChanged(f.key));
    const ok = await edit.save(section.id, keys);
    if (ok) {
      const resolvedTitle = title ?? translateOr(`einstellungen:sections.${section.id}`, section.title);
      notify({
        intent: 'success',
        title: t('notify.savedTitle', { title: resolvedTitle }),
        body: restartNeeded ? t('notify.restartNeeded') : undefined,
      });
    }
    return ok;
  };
}
