/**
 * Versionsauswahl in der Karte „Updates“: alle installierbaren Versionen (neuere und ältere) in
 * einer Liste, mit Datum und Hinweisen; „Diese Version installieren“ bzw. „Zurück auf …“ nach
 * Rückfrage. Ältere Versionen spielt der Dienst nur nach einer Sicherung ein.
 */
import { useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Caption1, Dropdown, Option, Spinner, Switch, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowDownload20Regular, ArrowUndo20Regular } from '@fluentui/react-icons';
import { FieldRow } from '../../../components/FieldRow';
import { ErrorMessage } from '../../../components/ErrorMessage';
import { ApiError } from '../../../api/client';
import { useUpdateVersions, type UpdateVersion } from '../../../api/update';
import { useFormat } from '../../../i18n/format';
import { useLayoutStyles } from '../../../theme/layout';

const useStyles = makeStyles({
  // Auswahl und Knopf untereinander, beide so breit wie die übrigen Knöpfe der Karte
  control: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'stretch',
    rowGap: tokens.spacingVerticalS,
    width: '100%',
  },
  dropdown: { minWidth: 0, width: '100%' },
  notes: { whiteSpace: 'pre-wrap', margin: 0, color: tokens.colorNeutralForeground2 },
  details: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  toggle: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalXS },
});

export function UpdateVersionPicker(props: {
  disabled: boolean;
  busy: boolean;
  onInstall: (version: string, downgrade: boolean) => void;
}): JSX.Element {
  const { t } = useTranslation('update');
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { formatDate } = useFormat();
  const id = useId();
  const [prerelease, setPrerelease] = useState(false);
  const query = useUpdateVersions(prerelease, true);
  const versions = useMemo(() => query.data?.versions ?? [], [query.data]);
  const [selected, setSelected] = useState<string | null>(null);

  // Vorauswahl: die neueste installierbare Version, die nicht die aktive ist
  useEffect(() => {
    if (selected !== null && versions.some((v) => v.version === selected)) return;
    const first = versions.find((v) => !v.current && !v.failed) ?? versions[0];
    setSelected(first ? first.version : null);
  }, [versions, selected]);

  const entry = versions.find((v) => v.version === selected) ?? null;
  const label = (v: UpdateVersion): string => {
    const marks: string[] = [];
    if (v.current) marks.push(t('versions.markCurrent'));
    else if (v.installed) marks.push(t('versions.markLocal'));
    if (v.newer) marks.push(t('versions.markNew'));
    if (v.prerelease) marks.push(t('versions.markPrerelease'));
    if (v.failed) marks.push(t('versions.markFailed'));
    const date = v.published ? formatDate(v.published) : '';
    const tail = [date, ...marks].filter(Boolean).join(', ');
    return tail ? `${v.version} (${tail})` : v.version;
  };

  const downgrade = entry !== null && !entry.newer && !entry.current;
  const canInstall = entry !== null && !entry.current && !entry.failed && !props.disabled;
  const sourceError = query.data?.error
    ? new ApiError(0, 'UpdateError', query.data.error.message, query.data.error.hint ?? '', 1, null, query.data.error.code)
    : null;

  return (
    <FieldRow
      htmlFor={`${id}-version`}
      label={t('versions.label')}
      help={t('versions.help')}
      details={
        <div className={styles.details}>
          <div className={styles.toggle}>
            <Switch
              id={`${id}-pre`}
              checked={prerelease}
              onChange={(_e, d) => setPrerelease(d.checked)}
              label={t('versions.prerelease')}
            />
          </div>
          {entry?.notes ? <p className={styles.notes}>{entry.notes}</p> : null}
          {downgrade ? <Caption1 className={layout.muted}>{t('versions.downgradeHint')}</Caption1> : null}
          {entry?.failed ? <Caption1 className={layout.muted}>{t('versions.failedHint')}</Caption1> : null}
          {sourceError ? <ErrorMessage error={sourceError} title={t('versions.sourceError')} /> : null}
          {query.isError ? <ErrorMessage error={query.error} onRetry={() => void query.refetch()} /> : null}
        </div>
      }
      control={
        <div className={styles.control}>
          {query.isLoading ? (
            <Spinner size="tiny" label={t('versions.loading')} />
          ) : (
            <Dropdown
              id={`${id}-version`}
              className={styles.dropdown}
              value={entry ? label(entry) : ''}
              selectedOptions={selected ? [selected] : []}
              onOptionSelect={(_e, d) => d.optionValue && setSelected(d.optionValue)}
              disabled={versions.length === 0}
              placeholder={t('versions.empty')}
            >
              {versions.map((v) => (
                <Option key={v.version} value={v.version} text={label(v)}>
                  {label(v)}
                </Option>
              ))}
            </Dropdown>
          )}
          <Button
            appearance="secondary"
            icon={props.busy ? <Spinner size="tiny" /> : downgrade ? <ArrowUndo20Regular /> : <ArrowDownload20Regular />}
            disabled={!canInstall || props.busy}
            aria-busy={props.busy || undefined}
            onClick={() => entry && props.onInstall(entry.version, downgrade)}
          >
            {downgrade && entry ? t('versions.downgrade', { version: entry.version }) : t('versions.install')}
          </Button>
        </div>
      }
    />
  );
}
