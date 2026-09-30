/**
 * Seite „Protokoll“: Protokolldateien des Druckdienstes, der Installation und der Updates aus dem
 * Ordner `logs`, vom Ende her gelesen. Werkzeugleiste mit Datei, Stufe, Suche, Zeilenzahl und
 * „Live“ (fortlaufend nachladen); Zeilen in Festbreitenschrift, nach Stufe eingefärbt. Tokens und
 * Passwörter blendet der Dienst aus. Das Tray öffnet diese Seite über „Protokoll“.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Caption1, Field, Input, Select, Switch, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import {
  ArrowClockwise20Regular,
  ArrowDownload20Regular,
  Copy20Regular,
  DocumentBulletList24Regular,
  Search20Regular,
} from '@fluentui/react-icons';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { ListToolbar, useToolbarSearchStyles } from '../../components/ListToolbar';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { Section } from '../../components/Section';
import { useNotify } from '../../components/NotifyProvider';
import { formatDateTime, formatNumber } from '../../i18n/format';
import { downloadLog, useLogContent, useLogList, type LogLevel, type LogLineJson, type LogQuery } from './api';

const LINE_CHOICES = [200, 500, 1000, 5000] as const;
const LEVEL_CHOICES: (LogLevel | '')[] = ['', 'INFO', 'WARNING', 'ERROR'];
const SEARCH_DELAY_MS = 300;

const useStyles = makeStyles({
  meta: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalXXS },
  select: { minWidth: '160px' },
  view: {
    margin: 0,
    maxHeight: '70vh',
    overflow: 'auto',
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase300,
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },
  line: { display: 'block', minHeight: tokens.lineHeightBase300 },
  debug: { color: tokens.colorNeutralForeground3 },
  warning: { color: tokens.colorStatusWarningForeground3 },
  error: { color: tokens.colorPaletteRedForeground1 },
  empty: { color: tokens.colorNeutralForeground3 },
});

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)} B`;
  if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024, { maximumFractionDigits: 1 })} KB`;
  return `${formatNumber(bytes / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
}

function levelClass(styles: ReturnType<typeof useStyles>, level: LogLineJson['level']): string | undefined {
  if (level === 'ERROR' || level === 'CRITICAL') return styles.error;
  if (level === 'WARNING') return styles.warning;
  if (level === 'DEBUG') return styles.debug;
  return undefined;
}

export default function ProtokollPage(): JSX.Element {
  const { t } = useTranslation('protokoll');
  const styles = useStyles();
  const searchStyles = useToolbarSearchStyles();
  const notify = useNotify();
  const [live, setLive] = useState(false);
  const [name, setName] = useState<string | null>(null);
  const [level, setLevel] = useState<LogLevel | ''>('');
  const [lines, setLines] = useState<number>(500);
  const [searchText, setSearchText] = useState('');
  const [search, setSearch] = useState('');
  const viewRef = useRef<HTMLPreElement>(null);
  const stickToEnd = useRef(true);

  const list = useLogList(live);
  const files = useMemo(() => list.data?.files ?? [], [list.data]);

  useEffect(() => {
    if (!list.data) return;
    if (name && files.some((f) => f.name === name)) return;
    const preferred = files.find((f) => f.name === list.data.daemon_log) ?? files[0];
    setName(preferred ? preferred.name : null);
  }, [files, list.data, name]);

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchText), SEARCH_DELAY_MS);
    return () => clearTimeout(id);
  }, [searchText]);

  const query: LogQuery | null = name ? { name, lines, level, search } : null;
  const content = useLogContent(query, live);

  useEffect(() => {
    const el = viewRef.current;
    if (el && stickToEnd.current) el.scrollTop = el.scrollHeight;
  }, [content.data]);

  const onScroll = () => {
    const el = viewRef.current;
    if (el) stickToEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  const copy = async () => {
    const text = (content.data?.lines ?? []).map((l) => l.text).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      notify({ intent: 'success', title: t('copied') });
    } catch {
      notify({ intent: 'error', title: t('copyFailed') });
    }
  };

  const download = async () => {
    if (!name) return;
    try {
      await downloadLog(name);
    } catch (err) {
      notify({ intent: 'error', title: t('downloadFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const refresh = () => {
    void list.refetch();
    void content.refetch();
  };

  const levelLabel = (value: LogLevel | ''): string => (value === '' ? t('level.all') : t(`level.${value.toLowerCase()}`));
  const current = files.find((f) => f.name === name);
  const shown = content.data?.lines ?? [];

  return (
    <>
      <PageHeader
        title={t('title')}
        subtitle={t('subtitle')}
        actions={
          <>
            <Button icon={<ArrowClockwise20Regular />} onClick={refresh} disabled={list.isFetching && !live}>
              {t('refresh')}
            </Button>
            <Button icon={<Copy20Regular />} onClick={() => void copy()} disabled={!shown.length}>
              {t('copy')}
            </Button>
            <Button icon={<ArrowDownload20Regular />} onClick={() => void download()} disabled={!name}>
              {t('download')}
            </Button>
          </>
        }
      />

      {list.isLoading ? <LoadingState variant="section" /> : null}
      {list.error ? <ErrorMessage error={list.error} title={t('listFailed')} onRetry={() => void list.refetch()} /> : null}
      {list.data && files.length === 0 ? (
        <EmptyState icon={<DocumentBulletList24Regular />} title={t('empty.title')} body={t('empty.body')} />
      ) : null}

      {files.length > 0 ? (
        <>
          <ListToolbar
            label={t('toolbarLabel')}
            actions={<Switch label={t('live')} checked={live} onChange={(_e, d) => setLive(d.checked)} />}
          >
            <Field label={t('file')}>
              <Select className={styles.select} value={name ?? ''} onChange={(_e, d) => setName(d.value)}>
                {files.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('levelLabel')}>
              <Select className={styles.select} value={level} onChange={(_e, d) => setLevel(d.value as LogLevel | '')}>
                {LEVEL_CHOICES.map((value) => (
                  <option key={value || 'all'} value={value}>
                    {levelLabel(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('lines')}>
              <Select className={styles.select} value={String(lines)} onChange={(_e, d) => setLines(Number(d.value))}>
                {LINE_CHOICES.map((n) => (
                  <option key={n} value={n}>
                    {t('linesValue', { count: n })}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('search')} className={searchStyles.search}>
              <Input
                type="search"
                contentBefore={<Search20Regular />}
                value={searchText}
                placeholder={t('searchPlaceholder')}
                onChange={(_e, d) => setSearchText(d.value)}
              />
            </Field>
          </ListToolbar>

          <Section
            title={name ?? ''}
            description={
              current ? (
                <span className={styles.meta}>
                  <span>{t('meta', { size: formatSize(current.size), time: formatDateTime(new Date(current.mtime * 1000)) })}</span>
                  {content.data?.truncated ? (
                    <Badge appearance="tint" color="informative" size="small">
                      {t('truncated', { count: shown.length })}
                    </Badge>
                  ) : null}
                  {live ? (
                    <Badge appearance="tint" color="success" size="small">
                      {t('liveActive')}
                    </Badge>
                  ) : null}
                </span>
              ) : undefined
            }
          >
            {content.error ? <ErrorMessage error={content.error} title={t('readFailed')} onRetry={() => void content.refetch()} /> : null}
            {content.isLoading ? <LoadingState variant="list" rows={6} /> : null}
            {content.data ? (
              <pre ref={viewRef} className={styles.view} onScroll={onScroll} aria-label={t('viewLabel', { name })} tabIndex={0}>
                {shown.length ? (
                  shown.map((line, i) => (
                    <span key={i} className={mergeClasses(styles.line, levelClass(styles, line.level))}>
                      {line.text || ' '}
                    </span>
                  ))
                ) : (
                  <Caption1 className={styles.empty}>{level || search ? t('noMatch') : t('fileEmpty')}</Caption1>
                )}
              </pre>
            ) : null}
          </Section>
        </>
      ) : null}
    </>
  );
}
