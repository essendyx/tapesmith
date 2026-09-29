/** Karte „Kalibrierung“: Längenfaktor messen, Vor-/Nachlauf, Kantentest. */
import { useId, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Input } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useNotify } from '../../../components/NotifyProvider';
import { usePrint } from '../../../components/usePrint';
import { postCalibrationLength, resetCalibrationLength, useCalibration } from '../api';
import { useConfirm } from '../../../components/ConfirmProvider';
import { FieldRow, FieldRows, ToggleControl } from '../FieldRow';

export function CalibrationCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const client = useQueryClient();
  const notify = useNotify();
  const confirm = useConfirm();
  const calibration = useCalibration();
  const print = usePrint();
  const [measuredMm, setMeasuredMm] = useState('100');
  const [keepLeader, setKeepLeader] = useState(false);
  const [leaderMm, setLeaderMm] = useState('');
  const [trailerMm, setTrailerMm] = useState('');
  const measuredId = useId();
  const keepLeaderId = useId();
  const leaderId = useId();
  const trailerId = useId();

  const onApply = async () => {
    const measured = Number(measuredMm.replace(',', '.'));
    if (!Number.isFinite(measured) || measured <= 0) {
      notify({ intent: 'error', title: t('calibration.notify.invalidLength') });
      return;
    }
    try {
      const r = await postCalibrationLength({
        measured_mm: measured,
        leader_mm: keepLeader && leaderMm.trim() !== '' ? Number(leaderMm.replace(',', '.')) : undefined,
        trailer_mm: keepLeader && trailerMm.trim() !== '' ? Number(trailerMm.replace(',', '.')) : undefined,
      });
      client.setQueryData(['calibration'], r);
      notify({ intent: 'success', title: t('calibration.notify.applied') });
    } catch (err) {
      notify({ intent: 'error', title: t('calibration.notify.failed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const onReset = async () => {
    const ok = await confirm({
      title: t('calibration.resetConfirmTitle'),
      message: t('calibration.resetConfirmMessage'),
      confirmText: t('calibration.reset'),
    });
    if (!ok) return;
    try {
      const r = await resetCalibrationLength();
      client.setQueryData(['calibration'], r);
      notify({ intent: 'success', title: t('calibration.notify.reset') });
    } catch (err) {
      notify({ intent: 'error', title: t('calibration.notify.failed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const c = calibration.data;
  return (
    <div id="kalibrierung">
      <Section title={t('calibration.title')} description={t('calibration.hint')}>
        <FieldRows>
          <FieldRow
            label={c ? t('calibration.factor', { value: c.length_factor.toFixed(4) }) : t('calibration.factorLabel')}
            help={c ? t('calibration.detail', { leader: c.leader_mm, trailer: c.trailer_mm, offset: c.content_offset }) : undefined}
            control={
              <Button appearance="secondary" disabled={!c || c.length_factor === 1} onClick={() => void onReset()}>
                {t('calibration.reset')}
              </Button>
            }
          />
          <FieldRow
            label={t('calibration.rulerLabel')}
            help={t('calibration.rulerHint')}
            control={
              <Button appearance="secondary" onClick={() => void print.run({ kind: 'calibration', which: 'ruler' })}>
                {t('calibration.printRuler')}
              </Button>
            }
          />
          <FieldRow
            htmlFor={measuredId}
            label={t('calibration.measuredLabel')}
            help={t('calibration.measuredHelp')}
            control={<Input id={measuredId} value={measuredMm} onChange={(_e, d) => setMeasuredMm(d.value)} contentAfter="mm" />}
          />
          <FieldRow
            htmlFor={keepLeaderId}
            label={t('calibration.keepLeader')}
            help={t('calibration.keepLeaderHelp')}
            align="end"
            control={<ToggleControl id={keepLeaderId} checked={keepLeader} onChange={setKeepLeader} />}
          />
          {keepLeader ? (
            <FieldRow
              htmlFor={leaderId}
              label={t('calibration.leaderLabel')}
              control={<Input id={leaderId} value={leaderMm} onChange={(_e, d) => setLeaderMm(d.value)} contentAfter="mm" />}
            />
          ) : null}
          {keepLeader ? (
            <FieldRow
              htmlFor={trailerId}
              label={t('calibration.trailerLabel')}
              control={<Input id={trailerId} value={trailerMm} onChange={(_e, d) => setTrailerMm(d.value)} contentAfter="mm" />}
            />
          ) : null}
          <FieldRow
            label={t('calibration.applyLabel')}
            help={t('calibration.applyHelp')}
            control={
              <Button appearance="primary" onClick={() => void onApply()}>
                {t('calibration.apply')}
              </Button>
            }
          />
          <FieldRow
            label={t('calibration.edgeLabel')}
            help={t('calibration.edgeHelp')}
            control={
              <Button appearance="secondary" onClick={() => void print.run({ kind: 'calibration', which: 'edge' })}>
                {t('calibration.printEdge')}
              </Button>
            }
          />
        </FieldRows>
      </Section>
    </div>
  );
}
