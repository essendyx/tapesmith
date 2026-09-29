/** Seite „Batterien“: Batteriestände aus Home Assistant und Wartungsetiketten,
 * Reiter über `?tab=`. */
import { useState } from 'react';
import {
  Badge,
  Button,
  Checkbox,
  Combobox,
  Input,
  Option,
  ProgressBar,
  Tab,
  TabList,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { printLabel } from '../../api/labels';
import type { LabelSource } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { ModuleSettingsButton } from '../../modules/ModuleSettingsButton';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { usePrintFlow } from '../../components/usePrint';
import { batterienKeys, postBatteryTable, setBatteryType, useBatteries } from './api';
import { BATTERY_TYPE_CHOICES } from './types';
import type { BatteryDeviceJson } from './types';
import { WartungView } from './WartungView';

type TabKey = 'batterien' | 'wartung';

function currentTab(value: string | null): TabKey {
  return value === 'wartung' ? 'wartung' : 'batterien';
}

function todayText(): string {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
}

const useStyles = makeStyles({
  page: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL },
  stack: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  tableWrap: { overflowX: 'auto', maxWidth: '100%' },
  filterRow: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' },
  filterInput: { width: '120px' },
  muted: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  levelCell: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: '90px' },
});

function BatterienListView(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('batterien');
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [unter, setUnter] = useState('');
  const below = unter.trim() !== '' && !Number.isNaN(Number(unter)) ? Number(unter) : undefined;
  const query = useBatteries(below);
  const devices = query.data?.devices ?? [];

  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [typeErrors, setTypeErrors] = useState<Record<string, string>>({});
  const [tableError, setTableError] = useState<unknown>(null);

  const printFlow = usePrintFlow<LabelSource>((req, opts) => printLabel(req, opts));
  const selectedIds = Object.entries(selected)
    .filter(([, v]) => v)
    .map(([id]) => id);

  async function changeType(entityId: string, raw: string): Promise<void> {
    setTypeErrors((m) => ({ ...m, [entityId]: '' }));
    try {
      await setBatteryType(entityId, raw.trim() === '' ? null : raw.trim());
      await queryClient.invalidateQueries({ queryKey: batterienKeys.list(below) });
    } catch (err) {
      const apiError = err instanceof ApiError ? err : new ApiError(0, 'Fehler', String(err)); // i18n-ignore (technische Kennung, nicht angezeigt)
      setTypeErrors((m) => ({ ...m, [entityId]: apiError.message }));
    }
  }

  async function printRow(device: BatteryDeviceJson): Promise<void> {
    await printFlow.run({
      kind: 'template',
      template: 'batterie',
      values: { geraet: device.device, raum: device.area, typ: device.battery_type, datum: todayText() },
    });
  }

  async function printAsSeries(): Promise<void> {
    setTableError(null);
    try {
      const result = await postBatteryTable({ entity_ids: selectedIds });
      navigate(`/vorlagen?vorlage=batterie&import=${encodeURIComponent(result.pending_id)}`);
    } catch (err) {
      setTableError(err);
    }
  }

  if (query.error) {
    return <ErrorMessage error={query.error} />;
  }

  return (
    <div className={styles.stack}>
      <Section
        title={t('list.sectionTitle')}
        description={t('list.sectionDescription')}
        actions={
          <div className={styles.filterRow}>
            <Input
              className={styles.filterInput}
              placeholder={t('list.filterPlaceholder')}
              value={unter}
              onChange={(_e, d) => setUnter(d.value)}
              aria-label={t('list.filterAria')}
            />
            <Button appearance="primary" disabled={selectedIds.length === 0} onClick={() => void printAsSeries()}>
              {t('list.printSeries')}
            </Button>
          </div>
        }
      >
        {query.isLoading ? <LoadingState variant="list" label={t('list.loading')} /> : null}
        {tableError ? <ErrorMessage error={tableError} /> : null}
        {!query.isLoading && devices.length === 0 ? (
          <EmptyState title={t('list.empty.title')} body={t('list.empty.body')} action={<ModuleSettingsButton module="homeassistant" appearance="secondary" />} />
        ) : devices.length > 0 ? (
          <div className={styles.tableWrap}>
            <Table size="small" aria-label={t('list.tableAriaLabel')}>
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>
                    <span className="p12-visually-hidden">{t('list.columns.select')}</span>
                  </TableHeaderCell>
                  <TableHeaderCell>{t('list.columns.device')}</TableHeaderCell>
                  <TableHeaderCell>{t('list.columns.area')}</TableHeaderCell>
                  <TableHeaderCell>{t('list.columns.level')}</TableHeaderCell>
                  <TableHeaderCell>{t('list.columns.type')}</TableHeaderCell>
                  <TableHeaderCell>
                    <span className="p12-visually-hidden">{t('list.columns.actions')}</span>
                  </TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {devices.map((device) => (
                  <TableRow key={device.entity_id}>
                    <TableCell>
                      <Checkbox
                        checked={selected[device.entity_id] ?? false}
                        onChange={(_e, d) =>
                          setSelected((m) => ({ ...m, [device.entity_id]: Boolean(d.checked) }))
                        }
                        aria-label={t('list.selectRowAria', { device: device.device })}
                      />
                    </TableCell>
                    <TableCell>{device.device}</TableCell>
                    <TableCell>{device.area}</TableCell>
                    <TableCell>
                      {device.low ? (
                        <Badge appearance="tint" color="danger">
                          {t('list.low')}
                        </Badge>
                      ) : (
                        <div className={styles.levelCell}>
                          <span>{device.level !== null ? t('list.levelText', { level: device.level }) : t('list.levelUnknown')}</span>
                          {device.level !== null ? (
                            <ProgressBar
                              value={device.level / 100}
                              color={device.level < 20 ? 'warning' : 'success'}
                              aria-label={t('list.levelProgressAria', { device: device.device })}
                              aria-valuetext={t('list.levelText', { level: device.level })}
                            />
                          ) : null}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Combobox
                        freeform
                        value={device.battery_type}
                        selectedOptions={device.battery_type ? [device.battery_type] : []}
                        onOptionSelect={(_e, d) => void changeType(device.entity_id, d.optionValue ?? '')}
                        onBlur={(e) => {
                          const value = (e.target as HTMLInputElement).value;
                          if (value !== device.battery_type) void changeType(device.entity_id, value);
                        }}
                        aria-label={t('list.typeAria', { device: device.device })}
                      >
                        {BATTERY_TYPE_CHOICES.map((choice) => (
                          <Option key={choice} value={choice}>
                            {choice}
                          </Option>
                        ))}
                      </Combobox>
                      {typeErrors[device.entity_id] ? (
                        <div className={styles.muted}>{typeErrors[device.entity_id]}</div>
                      ) : device.battery_type ? (
                        <div className={styles.muted}>{device.type_source}</div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Button size="small" onClick={() => void printRow(device)} disabled={printFlow.busy}>
                        {t('list.printRow')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </Section>
    </div>
  );
}

export default function BatterienPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('batterien');
  const [params, setParams] = useSearchParams();
  const tab = currentTab(params.get('tab'));

  const setTab = (next: TabKey) => {
    const p = new URLSearchParams(params);
    p.set('tab', next);
    setParams(p, { replace: true });
  };

  return (
    <div className={styles.page}>
      <PageHeader title={moduleTexts('homeassistant').name} subtitle={moduleTexts('homeassistant').description} />
      <TabList selectedValue={tab} onTabSelect={(_e, data) => setTab(data.value as TabKey)}>
        <Tab value="batterien">{t('tabs.batterien')}</Tab>
        <Tab value="wartung">{t('tabs.wartung')}</Tab>
      </TabList>
      <div>
        {tab === 'batterien' ? <BatterienListView /> : null}
        {tab === 'wartung' ? <WartungView /> : null}
      </div>
    </div>
  );
}
