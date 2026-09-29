/** Karte „Band und Rolle“: Bandprofile, Rollenstatus, neue Rolle, Rolle leer. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Body1,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  ProgressBar,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useNotify } from '../../../components/NotifyProvider';
import { qk, setCurrentTape, useTapes } from '../../../api/core';
import { postNewRoll, postRollEmpty, useRolls } from '../api';
import { FieldRow, FieldRows } from '../FieldRow';
import type { TapeInfo } from '../../../api/types';

const useStyles = makeStyles({
  swatches: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS },
  swatch: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    rowGap: tokens.spacingVerticalXS,
    width: '92px',
    padding: tokens.spacingHorizontalXS,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: 'transparent',
    // Name in normaler Textfarbe (sonst erbt der Knopf die blassere Systemfarbe, zu wenig Kontrast).
    color: tokens.colorNeutralForeground1,
    cursor: 'pointer',
    font: 'inherit',
  },
  swatchCurrent: { border: `${tokens.strokeWidthThick} solid ${tokens.colorBrandStroke1}` },
  chip: {
    width: '56px',
    height: '28px',
    borderRadius: tokens.borderRadiusSmall,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke3}`,
    display: 'grid',
    placeItems: 'center',
    fontSize: tokens.fontSizeBase100,
  },
  transparentBg: {
    backgroundImage: `linear-gradient(45deg, ${tokens.colorNeutralStroke3} 25%, transparent 25%, transparent 75%, ${tokens.colorNeutralStroke3} 75%), linear-gradient(45deg, ${tokens.colorNeutralStroke3} 25%, transparent 25%, transparent 75%, ${tokens.colorNeutralStroke3} 75%)`,
    backgroundSize: '8px 8px',
    backgroundPosition: '0 0, 4px 4px',
  },
  name: { fontSize: tokens.fontSizeBase200, textAlign: 'center', color: tokens.colorNeutralForeground1 },
  dialogField: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
});

function TapeSwatch(props: { tape: TapeInfo; onSelect: () => void }): JSX.Element {
  const styles = useStyles();
  const { tape } = props;
  return (
    <button
      type="button"
      className={mergeClasses(styles.swatch, tape.current && styles.swatchCurrent)}
      aria-pressed={tape.current}
      onClick={props.onSelect}
    >
      <span
        className={mergeClasses(styles.chip, tape.transparent && styles.transparentBg)}
        style={tape.transparent ? undefined : { backgroundColor: tape.background }}
      >
        <span style={{ color: tape.ink }}>Aa</span>
      </span>
      <span className={styles.name}>{tape.name}</span>
    </button>
  );
}

export function TapeRollCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const client = useQueryClient();
  const notify = useNotify();
  const tapes = useTapes();
  const rolls = useRolls();
  const [newRollOpen, setNewRollOpen] = useState(false);
  const [newRollM, setNewRollM] = useState('4');
  const [emptyOpen, setEmptyOpen] = useState(false);
  const [emptyAtM, setEmptyAtM] = useState('');

  const onSelectTape = async (id: string) => {
    try {
      const r = await setCurrentTape(id);
      client.setQueryData(qk.tapes, r);
    } catch (err) {
      notify({ intent: 'error', title: t('tape.notify.tapeChangeFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const onNewRoll = async () => {
    const m = Number(newRollM.replace(',', '.'));
    const length_mm = Number.isFinite(m) && m > 0 ? Math.round(m * 1000) : 4000;
    try {
      const r = await postNewRoll({ length_mm });
      client.setQueryData(qk.rolls, r);
      setNewRollOpen(false);
      notify({ intent: 'success', title: t('tape.notify.rollCreated') });
    } catch (err) {
      notify({ intent: 'error', title: t('tape.notify.rollCreateFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const onEmpty = async () => {
    const m = emptyAtM.trim() === '' ? undefined : Number(emptyAtM.replace(',', '.'));
    try {
      const r = await postRollEmpty({ at_mm: m !== undefined && Number.isFinite(m) ? Math.round(m * 1000) : null });
      client.setQueryData(qk.rolls, r);
      setEmptyOpen(false);
      notify({ intent: 'success', title: t('tape.notify.rollEmptied') });
    } catch (err) {
      notify({ intent: 'error', title: t('tape.notify.rollEmptyFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const current = rolls.data?.current ?? null;
  const usedFraction = current?.remaining_mm != null && current.length_mm > 0 ? current.used_mm / current.length_mm : null;

  return (
    <div id="band">
      <Section title={t('tape.title')}>
        <FieldRows>
          <FieldRow label={t('tape.profiles')} help={t('tape.profilesHelp')} layout="stacked">
            <div className={styles.swatches} role="group" aria-label={t('tape.profiles')}>
              {(tapes.data?.tapes ?? []).map((tape) => (
                <TapeSwatch key={tape.id} tape={tape} onSelect={() => void onSelectTape(tape.id)} />
              ))}
            </div>
          </FieldRow>
          <FieldRow
            label={t('tape.currentRoll')}
            help={current ? current.summary : t('tape.noRoll')}
            details={
              current ? (
                <>
                  <ProgressBar value={usedFraction ?? undefined} max={1} aria-label={t('tape.usedAria')} />
                  <Caption1>
                    {current.used_mm} mm / {current.length_mm} mm{current.spread_mm != null ? t('tape.estimated') : ''}
                  </Caption1>
                </>
              ) : undefined
            }
            control={
              <>
                <Button appearance="secondary" onClick={() => setNewRollOpen(true)}>
                  {t('tape.newRoll')}
                </Button>
                <Button appearance="secondary" onClick={() => setEmptyOpen(true)}>
                  {t('tape.rollEmpty')}
                </Button>
              </>
            }
          />
        </FieldRows>
      </Section>

      <Dialog open={newRollOpen} onOpenChange={(_e, d) => setNewRollOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('tape.newRollTitle')}</DialogTitle>
            <DialogContent>
              <Input
                value={newRollM}
                onChange={(_e, d) => setNewRollM(d.value)}
                aria-label={t('tape.lengthLabel')}
                contentAfter="m"
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => void onNewRoll()}>
                {t('tape.create')}
              </Button>
              <Button appearance="secondary" onClick={() => setNewRollOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={emptyOpen} onOpenChange={(_e, d) => setEmptyOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('tape.rollEmptyTitle')}</DialogTitle>
            <DialogContent className={styles.dialogField}>
              <Body1>{t('tape.rollEmptyBody')}</Body1>
              <Input
                value={emptyAtM}
                onChange={(_e, d) => setEmptyAtM(d.value)}
                aria-label={t('tape.emptyAtLabel')}
                placeholder={t('tape.emptyAtPlaceholder')}
                contentAfter="m"
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => void onEmpty()}>
                {t('tape.save')}
              </Button>
              <Button appearance="secondary" onClick={() => setEmptyOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
