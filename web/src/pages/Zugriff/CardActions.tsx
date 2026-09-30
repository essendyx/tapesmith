/**
 * Aktionen im Kartenkopf der Zugriffsseite: bei ungespeicherten Änderungen zuerst „Speichern“
 * (Primäraktion), dann „Verwerfen“, danach weitere Aktionen der Karte (z. B. „Testnachricht senden“).
 * Die Namen tragen den Kartentitel, damit mehrere offene Karten eindeutig bleiben.
 */
import type { ReactNode } from 'react';
import { Button } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

export function CardActions(props: {
  title: string;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
  children?: ReactNode;
}): JSX.Element {
  const { t } = useTranslation('zugriff');
  return (
    <>
      {props.dirty ? (
        <>
          <Button
            appearance="primary"
            disabled={props.saving}
            aria-busy={props.saving}
            aria-label={t('card.saveAria', { title: props.title })}
            onClick={props.onSave}
          >
            {t('common:actions.save')}
          </Button>
          <Button
            appearance="secondary"
            disabled={props.saving}
            aria-label={t('card.discardAria', { title: props.title })}
            onClick={props.onDiscard}
          >
            {t('card.discard')}
          </Button>
        </>
      ) : null}
      {props.children}
    </>
  );
}
