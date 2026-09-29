/**
 * Statusanzeige in der Kopfzeile: Punkt in Rollenfarbe plus Text, nie nur Farbe.
 * Kompakt: „P12 · verbunden“ ohne Transportpfad; der volle Text steht im Tooltip und im Detaildialog.
 */
import { useState } from 'react';
import { Button, makeStyles, Tooltip, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { useStatus } from '../api/core';
import type { Role, StatusJson } from '../api/types';
import { currentLanguage } from '../i18n';
import { StatusDetailDialog } from './StatusDetailDialog';
import { StatusDot } from './StatusDot';

const useStyles = makeStyles({
  chip: {
    borderRadius: tokens.borderRadiusCircular,
    paddingLeft: tokens.spacingHorizontalM,
    paddingRight: tokens.spacingHorizontalM,
    columnGap: tokens.spacingHorizontalS,
    fontWeight: tokens.fontWeightRegular,
    backgroundColor: tokens.colorSubtleBackgroundHover,
    maxWidth: '240px',
    minWidth: 0,
    '@media (max-width: 639px)': { maxWidth: '160px' },
  },
  label: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
});

const KNOWN_STATES = ['verbunden', 'getrennt', 'verbindet', 'offline', 'belegt', 'fehler', 'leased'];

type TFn = (key: string, opts?: Record<string, unknown>) => string;

/**
 * Kurzer Chip-Text. Deutsch: Server-Text ohne „(Transport)“; Englisch: aus Zustand und
 * bestätigten Werten gebaut (Rückfall auf den Server-Text bei unbekanntem Zustand).
 */
export function compactChipText(status: StatusJson, t: TFn): string {
  const { report, view } = status;
  const transport = report.state.transport;
  if (currentLanguage() === 'de') {
    return transport ? view.chip.replace(` (${transport})`, '') : view.chip;
  }
  const stateKey = report.state.leased ? 'leased' : report.state.state;
  if (!KNOWN_STATES.includes(stateKey)) return view.chip;
  let chip = t('status.chip', { state: t(`status.states.${stateKey}`) });
  const values = report.status?.values ?? {};
  const battery = values.battery;
  if (battery?.verified && typeof battery.value === 'number' && battery.value <= 100) {
    chip = t('status.battery', { chip, value: battery.value });
  }
  const lid = values.lid;
  if (lid?.verified && lid.value === 'offen') chip = t('status.lid', { chip });
  return chip;
}

export function StatusChip(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const status = useStatus();
  const [open, setOpen] = useState(false);
  const data = status.data;
  const tt: TFn = (key, opts) => String(t(key, opts));
  const text = data ? compactChipText(data, tt) : status.isError ? t('status.unknown') : t('status.loading');
  const role: Role = data?.view.role ?? 'secondary';
  const tooltip = data ? [data.view.chip, data.view.tooltip].filter((v, i, all) => v && all.indexOf(v) === i).join('\n') : t('status.tooltip');

  return (
    <>
      <Tooltip content={tooltip} relationship="description">
        <Button
          appearance="subtle"
          className={styles.chip}
          onClick={() => setOpen(true)}
          aria-label={t('status.chipLabel', { text })}
          aria-haspopup="dialog"
          data-testid="status-chip"
        >
          <StatusDot role={role} />
          <span className={styles.label}>{text}</span>
        </Button>
      </Tooltip>
      <StatusDetailDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
