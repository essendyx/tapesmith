/**
 * Wiederherstellung verwaister Entwürfe (nach Absturz, Neustart oder geschlossenem Fenster): Liste mit
 * Titel, Alter, Objektanzahl und Kennzeichen „ungespeichert“, je Eintrag ein Kontrollkästchen.
 */
import { useState } from 'react';
import {
  Badge,
  Button,
  Caption1,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import type { DraftInfo } from '../../../api/types';
import { useConfirm } from '../../../components/ConfirmProvider';
import { useFormat } from '../../../i18n/format';

const useStyles = makeStyles({
  surface: { maxWidth: '560px', width: 'calc(100vw - 32px)' },
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  intro: { margin: 0, color: tokens.colorNeutralForeground2 },
  list: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  entry: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS },
  line: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalS },
  title: { fontWeight: tokens.fontWeightSemibold },
  meta: { color: tokens.colorNeutralForeground3 },
});

export function RecoveryDialog(props: {
  drafts: DraftInfo[];
  onRestore(ids: string[]): void;
  onDiscard(ids: string[]): void;
  onLater(): void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const { formatRelative } = useFormat();
  const confirm = useConfirm();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(props.drafts.map((d) => d.id)));
  const ids = props.drafts.filter((d) => chosen.has(d.id)).map((d) => d.id);

  const toggle = (id: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(id);
    else next.delete(id);
    setChosen(next);
  };

  const discard = async () => {
    const ok = await confirm({
      title: t('recovery.discardTitle'),
      message: t('recovery.discardBody'),
      confirmText: t('recovery.discard'),
      cancelText: t('common:actions.cancel'),
      danger: true,
    });
    if (ok) props.onDiscard(ids);
  };

  return (
    <Dialog open onOpenChange={(_e, d) => (d.open ? undefined : props.onLater())}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>{t('recovery.title')}</DialogTitle>
          <DialogContent className={styles.content}>
            <p className={styles.intro}>{t('recovery.body')}</p>
            <ul className={styles.list} aria-label={t('recovery.list')}>
              {props.drafts.map((d) => (
                <li key={d.id}>
                  <Checkbox
                    checked={chosen.has(d.id)}
                    onChange={(_e, data) => toggle(d.id, data.checked === true)}
                    label={
                      <span className={styles.entry}>
                        <span className={styles.line}>
                          <span className={styles.title}>{d.title}</span>
                          {d.dirty ? (
                            <Badge appearance="tint" color="warning" size="small">
                              {t('recovery.unsaved')}
                            </Badge>
                          ) : null}
                        </span>
                        <Caption1 className={styles.meta}>
                          {[formatRelative(d.updated), t('recovery.objects', { count: d.objects })].join(' · ')}
                        </Caption1>
                      </span>
                    }
                  />
                </li>
              ))}
            </ul>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={ids.length === 0} onClick={() => props.onRestore(ids)}>
              {t('recovery.restore')}
            </Button>
            <Button disabled={ids.length === 0} onClick={() => void discard()}>
              {t('recovery.discard')}
            </Button>
            <Button onClick={props.onLater}>{t('recovery.later')}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
