/**
 * Karte „Drucker“: Status, Suchen und testen, Testlabel. MAC-Adresse und Transport stehen unter
 * „Erweitert“, Zeitlimits nur in config.json.
 */
import { useId, useState } from 'react';
import { Badge, Body1, Button, Input, MessageBar, MessageBarBody, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowClockwise20Regular, CheckmarkCircle20Filled, ErrorCircle20Filled, Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { refreshStatus, useStatus } from '../../../api/core';
import { ApiError } from '../../../api/client';
import { usePrint } from '../../../components/usePrint';
import { postSetup, useSettingsPorts } from '../api';
import { StatusDetailList } from './StatusDetailList';
import { FieldRow, FieldRows, ToggleControl } from '../FieldRow';
import type { SetupJson } from '../../../api/types';

const useStyles = makeStyles({
  steps: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS, margin: 0, padding: 0, listStyle: 'none' },
  step: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'flex-start' },
  stepOk: { color: tokens.colorPaletteGreenForeground1, flexShrink: 0 },
  stepBad: { color: tokens.colorPaletteRedForeground1, flexShrink: 0 },
  stepText: { display: 'flex', flexDirection: 'column' },
  hint: { color: tokens.colorNeutralForeground3 },
  result: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, paddingTop: tokens.spacingVerticalM, paddingBottom: tokens.spacingVerticalM },
});

export function ConnectionCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const status = useStatus();
  const ports = useSettingsPorts();
  const print = usePrint();
  const [refreshing, setRefreshing] = useState(false);
  const [port, setPort] = useState<string>('');
  const [withTestLabel, setWithTestLabel] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SetupJson | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const portId = useId();
  const testLabelId = useId();

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshStatus();
    } finally {
      setRefreshing(false);
    }
  };

  const onRunSetup = async () => {
    setRunning(true);
    setSetupError(null);
    setResult(null);
    try {
      const r = await postSetup({ port: port || null, test_label: withTestLabel });
      setResult(r);
    } catch (err) {
      setSetupError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const view = status.data?.view;

  return (
    <div id="verbindung">
      <Section title={t('connection.title')}>
        <FieldRows>
          <FieldRow
            label={t('connection.status')}
            badges={
              <Badge appearance="tint" color={view?.role === 'error' ? 'danger' : view?.role === 'warning' ? 'warning' : 'success'}>
                {view?.chip ?? t('connection.unknown')}
              </Badge>
            }
            details={view?.detail ? <StatusDetailList detail={view.detail} /> : undefined}
            control={
              <Button
                appearance="secondary"
                icon={refreshing ? <Spinner size="tiny" /> : <ArrowClockwise20Regular />}
                disabled={refreshing}
                onClick={() => void onRefresh()}
              >
                {t('connection.refresh')}
              </Button>
            }
          />
          <FieldRow
            htmlFor={portId}
            label={t('connection.portLabel')}
            help={t('connection.portHelp')}
            control={
              <>
                <Input
                  id={portId}
                  placeholder={t('connection.portPlaceholder')}
                  value={port}
                  list="verbindung-ports"
                  onChange={(_e, d) => setPort(d.value)}
                />
                <datalist id="verbindung-ports">
                  {(ports.data?.transports ?? []).map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </datalist>
              </>
            }
          />
          <FieldRow
            htmlFor={testLabelId}
            label={t('connection.testLabelCheckbox')}
            help={t('connection.testLabelHelp')}
            align="end"
            control={<ToggleControl id={testLabelId} checked={withTestLabel} onChange={setWithTestLabel} />}
          />
          <FieldRow
            label={t('connection.wizardTitle')}
            help={t('connection.wizardHelp')}
            control={
              <Button
                appearance="primary"
                icon={running ? <Spinner size="tiny" appearance="inverted" /> : <Search20Regular />}
                disabled={running}
                onClick={() => void onRunSetup()}
              >
                {t('connection.search')}
              </Button>
            }
          />
          {setupError || result ? (
            <div className={styles.result}>
              {setupError ? (
                <MessageBar intent="error">
                  <MessageBarBody>{setupError}</MessageBarBody>
                </MessageBar>
              ) : null}
              {result ? (
                <ul className={styles.steps}>
                  {result.steps.map((step) => (
                    <li key={step.name} className={styles.step}>
                      {step.ok ? (
                        <CheckmarkCircle20Filled className={styles.stepOk} aria-hidden="true" />
                      ) : (
                        <ErrorCircle20Filled className={styles.stepBad} aria-hidden="true" />
                      )}
                      <span className={styles.stepText}>
                        <Body1>
                          <strong>{step.name}</strong>
                          {step.detail ? `: ${step.detail}` : ''}
                        </Body1>
                        {step.hint ? <span className={styles.hint}>{step.hint}</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <FieldRow
            label={t('connection.printTestLabel')}
            help={t('connection.printTestHelp')}
            control={
              <Button appearance="secondary" disabled={print.busy} onClick={() => void print.run({ kind: 'test' })}>
                {t('connection.printTest')}
              </Button>
            }
          />
        </FieldRows>
      </Section>
    </div>
  );
}
