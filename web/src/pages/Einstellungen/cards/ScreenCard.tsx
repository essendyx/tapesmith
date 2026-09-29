/** Karte „Bildschirm“: Kalibrierung mit einer echten Kreditkarte (85,6 × 53,98 mm). */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Body1,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useNotify } from '../../../components/NotifyProvider';
import { qk, useAppInfo } from '../../../api/core';
import { patchSettings } from '../api';
import { cardWidthPxFromScreenPxPerMm, screenPxPerMmFromCardWidth } from '../format';
import { FieldRow, FieldRows } from '../FieldRow';

const CARD_HEIGHT_MM = 53.98;
const DEFAULT_WIDTH_PX = cardWidthPxFromScreenPxPerMm(96 / 25.4);

const useStyles = makeStyles({
  row: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  stage: { display: 'flex', justifyContent: 'center', padding: tokens.spacingVerticalL },
  outline: {
    border: `2px dashed ${tokens.colorBrandStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    display: 'grid',
    placeItems: 'center',
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
  },
});

export function ScreenCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const client = useQueryClient();
  const notify = useNotify();
  const app = useAppInfo();
  const [open, setOpen] = useState(false);
  const [widthPx, setWidthPx] = useState<number>(() => cardWidthPxFromScreenPxPerMm(app.data?.screen_px_per_mm ?? 96 / 25.4) || DEFAULT_WIDTH_PX);

  const openDialog = () => {
    setWidthPx(cardWidthPxFromScreenPxPerMm(app.data?.screen_px_per_mm ?? 96 / 25.4) || DEFAULT_WIDTH_PX);
    setOpen(true);
  };

  const apply = async () => {
    const value = screenPxPerMmFromCardWidth(widthPx);
    try {
      const fresh = await patchSettings({ 'gui.screen_px_per_mm': value });
      client.setQueryData(qk.settings, fresh);
      await client.invalidateQueries({ queryKey: qk.app });
      setOpen(false);
      notify({ intent: 'success', title: t('screen.notify.applied') });
    } catch (err) {
      notify({ intent: 'error', title: t('screen.notify.applyFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const reset = async () => {
    try {
      const fresh = await patchSettings({ 'gui.screen_px_per_mm': null });
      client.setQueryData(qk.settings, fresh);
      await client.invalidateQueries({ queryKey: qk.app });
      setOpen(false);
      notify({ intent: 'success', title: t('screen.notify.resetDone') });
    } catch (err) {
      notify({ intent: 'error', title: t('screen.notify.resetFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const heightPx = (widthPx / 85.6) * CARD_HEIGHT_MM;
  const current = app.data?.screen_px_per_mm;

  return (
    <div id="bildschirm">
      <Section title={t('screen.title')}>
        <FieldRows>
          <FieldRow
            label={current != null ? t('screen.current', { value: current.toFixed(3) }) : t('screen.uncalibrated')}
            help={t('screen.hint')}
            control={
              <Button appearance="secondary" onClick={openDialog}>
                {t('screen.calibrate')}
              </Button>
            }
          />
        </FieldRows>
      </Section>

      <Dialog open={open} onOpenChange={(_e, d) => setOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('screen.dialogTitle')}</DialogTitle>
            <DialogContent>
              <Body1>{t('screen.dialogBody')}</Body1>
              <div className={styles.stage}>
                <div className={styles.outline} style={{ width: `${widthPx}px`, height: `${heightPx}px` }}>
                  {t('screen.outline')}
                </div>
              </div>
              <div className={styles.row}>
                <Button appearance="secondary" onClick={() => setWidthPx((w) => Math.max(50, w - 1))}>
                  −
                </Button>
                <Input
                  type="number"
                  value={widthPx.toFixed(1)}
                  aria-label={t('screen.widthLabel')}
                  contentAfter="px"
                  onChange={(_e, d) => {
                    const n = Number(d.value);
                    if (Number.isFinite(n)) setWidthPx(n);
                  }}
                />
                <Button appearance="secondary" onClick={() => setWidthPx((w) => w + 1)}>
                  +
                </Button>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => void apply()}>
                {t('screen.apply')}
              </Button>
              <Button appearance="secondary" onClick={() => void reset()}>
                {t('screen.reset')}
              </Button>
              <Button appearance="secondary" onClick={() => setOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
