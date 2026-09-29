/**
 * Seite „Statistik": Bandverbrauch nach Monat, Vorlage, Quelle, Art oder Rolle.
 * Balkendiagramm ohne Bibliothek (reines CSS, mit Achse und Tooltip), daneben die Tabelle als Textalternative.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Caption1, ProgressBar, ToggleButton, Tooltip, makeStyles, tokens } from '@fluentui/react-components';
import { apiGet } from '../../api/client';
import { qk } from '../../api/core';
import type { RollUsageJson, StatsJson } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { PageHeader } from '../../components/PageHeader';
import { Section } from '../../components/Section';
import { useFormat } from '../../i18n/format';
import { dateOnly } from '../Verlauf/time';
import { TableScroll } from '../../components/TableScroll';

const GROUP_KEYS = ['monat', 'vorlage', 'quelle', 'art', 'rolle'] as const;

const useStyles = makeStyles({
  toolbar: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalM, alignItems: 'flex-end', marginBottom: tokens.spacingVerticalL },
  groupRow: { display: 'flex', columnGap: tokens.spacingHorizontalXS, flexWrap: 'wrap' },
  dateField: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS },
  dateInput: {
    font: 'inherit',
    padding: `${tokens.spacingVerticalSNudge} ${tokens.spacingHorizontalSNudge}`,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
  },
  kpis: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalL, rowGap: tokens.spacingVerticalM, marginBottom: tokens.spacingVerticalL },
  kpi: {
    flex: '1 1 160px',
    padding: tokens.spacingVerticalL,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
  },
  kpiValue: { fontSize: tokens.fontSizeHero700, fontWeight: tokens.fontWeightSemibold },
  chartAndTable: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL },
  chart: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  chartAxis: {
    display: 'flex',
    justifyContent: 'space-between',
    color: tokens.colorNeutralForeground3,
    paddingBottom: tokens.spacingVerticalXS,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  chartBars: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  chartBarRow: { display: 'flex', alignItems: 'center' },
  barTrack: {
    flexGrow: 1,
    height: '24px',
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground3,
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
  },
  bar: {
    height: '100%',
    minWidth: '2px',
    backgroundColor: tokens.colorBrandBackground,
    borderRadius: tokens.borderRadiusMedium,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingRight: tokens.spacingHorizontalS,
    boxSizing: 'border-box',
  },
  barValue: { color: tokens.colorNeutralForegroundOnBrand, fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase200, whiteSpace: 'nowrap' },
  table: { width: '100%', borderCollapse: 'collapse', marginTop: tokens.spacingVerticalL },
  th: { textAlign: 'left', padding: tokens.spacingVerticalS, borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`, color: tokens.colorNeutralForeground3, fontWeight: tokens.fontWeightSemibold },
  td: { padding: tokens.spacingVerticalS, borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}` },
  rollBar: { minWidth: '96px' },
});

export default function StatistikPage(): JSX.Element {
  const { t } = useTranslation('statistik');
  const styles = useStyles();
  const { formatNumber } = useFormat();
  const [group, setGroup] = useState<(typeof GROUP_KEYS)[number]>('monat');
  const [since, setSince] = useState('');

  const formatMeters = (mm: number): string => t('unit.meter', { value: formatNumber(mm / 1000, { maximumFractionDigits: 1 }) });

  const statsQuery = useQuery({
    queryKey: [...qk.stats, group, since],
    queryFn: ({ signal }) =>
      apiGet<StatsJson>(`/api/v1/stats?by=${encodeURIComponent(group)}${since ? `&since=${encodeURIComponent(since)}` : ''}`, signal),
  });
  const rollsQuery = useQuery({
    queryKey: [...qk.rolls, 'usage'],
    queryFn: ({ signal }) => apiGet<{ rolls: RollUsageJson[] }>('/api/v1/stats/rolls', signal),
  });

  const rows = useMemo(() => statsQuery.data?.rows ?? [], [statsQuery.data]);
  const totals = statsQuery.data?.totals;
  const rolls = rollsQuery.data?.rolls ?? [];
  const maxTape = useMemo(() => Math.max(1, ...rows.map((r) => r.tape_mm)), [rows]);

  return (
    <>
      <PageHeader title={t('title')} />
      <div className={styles.toolbar}>
        <div className={styles.groupRow} role="group" aria-label={t('a11y.groupBy')}>
          {GROUP_KEYS.map((key) => (
            <ToggleButton key={key} checked={group === key} onClick={() => setGroup(key)}>
              {t(`groups.${key}`)}
            </ToggleButton>
          ))}
        </div>
        <label className={styles.dateField}>
          <Caption1>{t('since')}</Caption1>
          <input
            className={styles.dateInput}
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            aria-label={t('a11y.since')}
          />
        </label>
      </div>

      {totals ? (
        <div className={styles.kpis}>
          <div className={styles.kpi}>
            <Caption1>{t('kpi.jobs')}</Caption1>
            <span className={styles.kpiValue}>{formatNumber(totals.jobs)}</span>
          </div>
          <div className={styles.kpi}>
            <Caption1>{t('kpi.labels')}</Caption1>
            <span className={styles.kpiValue}>{formatNumber(totals.labels)}</span>
          </div>
          <div className={styles.kpi}>
            <Caption1>{t('kpi.tape')}</Caption1>
            <span className={styles.kpiValue}>{formatMeters(totals.tape_mm)}</span>
          </div>
        </div>
      ) : null}

      {rows.length === 0 ? (
        <EmptyState title={t('empty.title')} body={t('empty.body')} />
      ) : (
        <Section title={t('chart.title')} description={t('chart.description')}>
          <div className={styles.chartAndTable}>
            <div className={styles.chart} aria-label={t('chart.label')}>
              <div className={styles.chartAxis}>
                <Caption1>{formatMeters(0)}</Caption1>
                <Caption1>{formatMeters(maxTape / 2)}</Caption1>
                <Caption1>{formatMeters(maxTape)}</Caption1>
              </div>
              <div className={styles.chartBars}>
                {rows.map((row) => (
                  <Tooltip key={row.key} content={t('chart.tooltip', { key: row.key, value: formatMeters(row.tape_mm) })} relationship="label" withArrow>
                    <div className={styles.chartBarRow} tabIndex={0}>
                      <div className={styles.barTrack}>
                        <div className={styles.bar} style={{ width: `${Math.max(2, (row.tape_mm / maxTape) * 100)}%` }}>
                          <span className={styles.barValue}>{formatMeters(row.tape_mm)}</span>
                        </div>
                      </div>
                    </div>
                  </Tooltip>
                ))}
              </div>
            </div>
            <TableScroll label={t('table.ariaGroups')}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.th}>{t('table.group')}</th>
                  <th className={styles.th}>{t('table.jobs')}</th>
                  <th className={styles.th}>{t('table.labels')}</th>
                  <th className={styles.th}>{t('table.tape')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td className={styles.td}>{row.key}</td>
                    <td className={styles.td}>{formatNumber(row.jobs)}</td>
                    <td className={styles.td}>{formatNumber(row.labels)}</td>
                    <td className={styles.td}>{formatMeters(row.tape_mm)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </TableScroll>
          </div>
        </Section>
      )}

      <Section title={t('rolls.title')} description={t('rolls.description')}>
        {rolls.length === 0 ? (
          <EmptyState title={t('rolls.empty')} />
        ) : (
          <TableScroll label={t('table.ariaRolls')}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.th}>{t('table.roll')}</th>
                <th className={styles.th}>{t('table.started')}</th>
                <th className={styles.th}>{t('table.nominal')}</th>
                <th className={styles.th}>{t('table.used')}</th>
                <th className={styles.th}>{t('table.jobs')}</th>
                <th className={styles.th}>{t('table.finished')}</th>
                <th className={styles.th}>{t('table.factor')}</th>
              </tr>
            </thead>
            <tbody>
              {rolls.map((roll, i) => (
                <tr key={`${roll.tape_id}-${roll.started}-${i}`}>
                  <td className={styles.td}>{roll.tape_name}</td>
                  <td className={styles.td}>{dateOnly(roll.started)}</td>
                  <td className={styles.td}>{formatMeters(roll.length_mm)}</td>
                  <td className={styles.td}>
                    <div className={styles.rollBar}>
                      <ProgressBar
                        value={Math.min(1, roll.used_mm / Math.max(1, roll.length_mm))}
                        aria-label={t('rolls.usedAria', { tape: roll.tape_name })}
                      />
                      <Caption1>{formatMeters(roll.used_mm)}</Caption1>
                    </div>
                  </td>
                  <td className={styles.td}>{formatNumber(roll.jobs)}</td>
                  <td className={styles.td}>{roll.finished ? t('table.yes') : t('table.no')}</td>
                  <td className={styles.td}>{roll.factor.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        )}
      </Section>
    </>
  );
}
