/**
 * Detailwerte des Druckerstatus als zweispaltige Liste (`dl`): Beschriftung links, Wert rechts,
 * lange Werte brechen um. Der Server liefert die Zeilen als deutschen Text „Name: Wert“; die
 * bekannten Beschriftungen und der Wert „nicht verfügbar“ werden hier übersetzt, alle übrigen
 * Werte erscheinen unverändert.
 */
import { Fragment } from 'react';
import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { detailPairs } from '../../../shell/StatusDetailDialog';

/** Beschriftungen aus `tapesmith.statusview` -> Schlüssel unter `connection.detail.terms`. */
const TERM_KEYS: Record<string, string> = {
  Zustand: 'state', // i18n-ignore
  Verbindung: 'connection', // i18n-ignore
  Akku: 'battery', // i18n-ignore
  Deckel: 'lid', // i18n-ignore
  Band: 'tape', // i18n-ignore
  Firmware: 'firmware', // i18n-ignore
  Seriennummer: 'serial', // i18n-ignore
  Medium: 'media', // i18n-ignore
  MAC: 'mac', // i18n-ignore
  Transport: 'transport', // i18n-ignore
  'Letzte Antwort': 'lastResponse', // i18n-ignore
  'Zuletzt abgefragt': 'checked', // i18n-ignore
  'Letzter Fehler': 'lastError', // i18n-ignore
};

/** Wert, den der Server für fehlende Angaben schreibt (`statusview.MISSING`). */
export const MISSING_VALUE = 'nicht verfügbar'; // i18n-ignore

const useStyles = makeStyles({
  list: {
    display: 'grid',
    gridTemplateColumns: 'minmax(6em, max-content) minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXXS,
    margin: 0,
    paddingTop: tokens.spacingVerticalXS,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  term: { color: tokens.colorNeutralForeground2 },
  value: {
    margin: 0,
    minWidth: 0,
    color: tokens.colorNeutralForeground1,
    overflowWrap: 'anywhere',
    whiteSpace: 'pre-wrap',
  },
  missing: { color: tokens.colorNeutralForeground3 },
});

export function StatusDetailList(props: { detail: string }): JSX.Element | null {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const pairs = detailPairs(props.detail);
  if (pairs.length === 0) return null;
  return (
    <dl className={styles.list} data-testid="connection-status-detail" aria-label={t('connection.detail.label')}>
      {pairs.map((p, i) => {
        const key = TERM_KEYS[p.term];
        const missing = p.value.trim() === MISSING_VALUE;
        return (
          <Fragment key={`${p.term}-${i}`}>
            <dt className={styles.term}>{key ? t(`connection.detail.terms.${key}`) : p.term}</dt>
            <dd className={mergeClasses(styles.value, missing && styles.missing)}>
              {missing ? t('connection.detail.notAvailable') : p.value}
            </dd>
          </Fragment>
        );
      })}
    </dl>
  );
}
