/** Karte „Zusatzdienste“: Status der Addons (Hotfolder, MQTT, Telegram, Update). */
import { Body1, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/EmptyState';
import { FieldRow, FieldRows } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import type { AddonStatus } from './types';

const useStyles = makeStyles({
  status: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalS,
    minWidth: 0,
    color: tokens.colorNeutralForeground2,
    overflowWrap: 'anywhere',
    textAlign: 'right',
  },
  dot: { width: '10px', height: '10px', borderRadius: tokens.borderRadiusCircular, flexShrink: 0 },
  dotOk: { backgroundColor: tokens.colorPaletteGreenForeground1 },
  dotOff: { backgroundColor: tokens.colorNeutralForeground4 },
  dotError: { backgroundColor: tokens.colorPaletteRedForeground1 },
});

export function AddonsCard(props: { addons: AddonStatus[] }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const names: Record<AddonStatus['name'], string> = {
    hotfolder: t('addons.hotfolder'),
    mqtt: t('addons.mqtt'),
    telegram: t('addons.telegram'),
    update: t('addons.update'),
  };
  return (
    <Section id="dienste" title={t('addons.title')}>
      {props.addons.length === 0 ? (
        <EmptyState compact title={t('addons.empty')} />
      ) : (
        <FieldRows>
          {props.addons.map((a) => {
            const state = a.error ? t('addons.error', { message: a.error }) : a.running ? t('addons.running') : t('addons.stopped');
            const detail = a.detail && a.detail !== state ? a.detail : undefined;
            return (
              <FieldRow
                key={a.name}
                label={names[a.name]}
                help={detail}
                align="end"
                control={
                  <Body1 className={styles.status}>
                    <span
                      className={mergeClasses(styles.dot, a.error ? styles.dotError : a.running ? styles.dotOk : styles.dotOff)}
                      aria-hidden="true"
                    />
                    {state}
                  </Body1>
                }
              />
            );
          })}
        </FieldRows>
      )}
    </Section>
  );
}
