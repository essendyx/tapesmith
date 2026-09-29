/** Karte „Zusatzdienste“: Status der Addons (Hotfolder, MQTT, Telegram, Update). */
import { Body1, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import type { AddonStatus } from './types';

const useStyles = makeStyles({
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  row: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
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
      <div className={styles.list}>
        {props.addons.map((a) => (
          <div className={styles.row} key={a.name}>
            <span
              className={`${styles.dot} ${a.error ? styles.dotError : a.running ? styles.dotOk : styles.dotOff}`}
              aria-hidden="true"
            />
            <Body1>
              <strong>{names[a.name]}</strong>: {a.error ? t('addons.error', { message: a.error }) : a.running ? t('addons.running') : t('addons.stopped')}
              {a.detail ? ` (${a.detail})` : ''}
            </Body1>
          </div>
        ))}
      </div>
    </Section>
  );
}
