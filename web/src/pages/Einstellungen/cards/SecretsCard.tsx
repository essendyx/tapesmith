/**
 * Karte „Tokens und Passwörter“: alle Geheimwerte an einer Stelle, auch die ausgeschalteter
 * Module. Je Zeile Zustand, Speichern bzw. Ersetzen, Entfernen, Übernahme aus einer externen Quelle
 * und der Weg zur Einrichtung des Dienstes; oben „Alle aus externen Quellen übernehmen“.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Spinner, Text, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowDownload20Regular, Open16Regular, PuzzlePiece16Regular } from '@fluentui/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/client';
import { adoptAllSecrets, refreshSecretViews, useSecrets, type SecretSlot } from '../../../api/secrets';
import { FieldRows } from '../../../components/FieldRow';
import { useNotify } from '../../../components/NotifyProvider';
import { Section } from '../../../components/Section';
import { SecretField } from '../../../components/SecretField';
import { moduleTexts } from '../../../modules';
import { MODULES_CARD_ID } from '../sectionIds';

export const SECRETS_CARD_ID = 'tokens';

const useStyles = makeStyles({
  empty: { color: tokens.colorNeutralForeground3 },
});

/** Kann „Alle übernehmen“ für diesen Slot etwas tun? */
function adoptable(slot: SecretSlot): boolean {
  return slot.source === 'extern' && slot.set;
}

function SecretRow(props: { slot: SecretSlot }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const navigate = useNavigate();
  const { slot } = props;
  const moduleName = slot.module ? moduleTexts(slot.module).name : undefined;
  const moduleOff = Boolean(slot.module) && slot.module_enabled === false;
  const help = moduleOff
    ? t('secrets.moduleOffHelp', { module: moduleName })
    : slot.module
      ? t('secrets.moduleHelp', { module: moduleName })
      : t('secrets.accessHelp');
  const action = moduleOff ? (
    <Button
      size="small"
      appearance="subtle"
      icon={<PuzzlePiece16Regular />}
      onClick={() => navigate(`/einstellungen?abschnitt=${MODULES_CARD_ID}`)}
    >
      {t('secrets.enableModule')}
    </Button>
  ) : (
    <Button size="small" appearance="subtle" icon={<Open16Regular />} onClick={() => navigate(slot.target ?? '/zugriff')}>
      {slot.module ? t('secrets.openSettings') : t('secrets.openAccess')}
    </Button>
  );
  return (
    <SecretField
      slotId={slot.id}
      label={slot.label}
      help={help}
      extraBadges={
        moduleOff ? (
          <Badge appearance="outline" size="small" color="subtle">
            {t('secrets.moduleOff')}
          </Badge>
        ) : undefined
      }
      extraActions={action}
    />
  );
}

export function SecretsCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const notify = useNotify();
  const queryClient = useQueryClient();
  const secrets = useSecrets();
  const [busy, setBusy] = useState(false);
  const slots = secrets.data?.slots ?? [];
  const candidates = slots.filter(adoptable).length;

  const adoptAll = async () => {
    setBusy(true);
    try {
      const result = await adoptAllSecrets();
      queryClient.setQueryData(['secrets'], { slots: result.slots });
      refreshSecretViews(queryClient);
      const skipped = result.skipped.map((s) => `${s.label}: ${s.reason}`).join(' · ');
      notify({
        intent: result.skipped.length ? 'warning' : 'success',
        title: t('secrets.adoptAllDone', { count: result.adopted.length }),
        body: result.skipped.length
          ? t('secrets.adoptAllSkipped', {
              count: result.skipped.length,
              list: skipped,
            })
          : undefined,
      });
    } catch (err) {
      notify({
        intent: 'error',
        title: t('secrets.adoptAllFailed'),
        body: err instanceof ApiError || err instanceof Error ? err.message : String(err),
        hint: err instanceof ApiError ? err.hint || undefined : undefined,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      id={SECRETS_CARD_ID}
      title={t('secrets.title')}
      description={t('secrets.description')}
      actions={
        <Button
          appearance="secondary"
          icon={busy ? <Spinner size="tiny" /> : <ArrowDownload20Regular />}
          disabled={busy || candidates === 0}
          aria-busy={busy}
          onClick={() => void adoptAll()}
        >
          {t('secrets.adoptAll')}
        </Button>
      }
    >
      {secrets.isLoading ? <Spinner size="small" label={t('loading')} /> : null}
      {!secrets.isLoading && slots.length === 0 ? <Text className={styles.empty}>{t('secrets.none')}</Text> : null}
      {slots.length ? (
        <FieldRows>
          {slots.map((slot) => (
            <SecretRow key={slot.id} slot={slot} />
          ))}
        </FieldRows>
      ) : null}
    </Section>
  );
}
