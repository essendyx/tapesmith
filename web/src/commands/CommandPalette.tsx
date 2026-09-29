/** Kommandopalette (übersetzt): Suchfeld, gruppierte Liste, Pfeiltasten, Eingabe, Esc. */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Dialog, DialogSurface, Input, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { ChevronRight16Regular, Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { i18n } from '../i18n';
import { searchCommands } from './fuzzy';
import { isEnabled, type CommandDef } from './registry';

/** Gruppen-Kennung „Zuletzt benutzt“. */
export const RECENT_GROUP = 'recent';

/** Bekannte Gruppen in Anzeige-Reihenfolge (Schlüssel unter `commands:groups`). */
const GROUP_ORDER = ['navigation', 'print', 'templates', 'printer', 'queue', 'drives', 'settings', 'appearance', 'help'];
const KNOWN_GROUPS = [...GROUP_ORDER, 'recent', 'tapes', 'editor', 'schnelldruck'];

/**
 * Gruppen-Kennung eines Befehls: bekannte Kennung („print“) oder ein deutscher Gruppenname, wie ihn
 * Seiten bisher übergeben („Drucken“), wird auf die Kennung abgebildet; alles andere bleibt Text.
 */
export function groupKey(group: string): string {
  if (KNOWN_GROUPS.includes(group)) return group;
  const de = i18n.getFixedT('de', 'commands');
  return KNOWN_GROUPS.find((k) => de(`groups.${k}`) === group) ?? group;
}

/** Anzeigename einer Gruppe in der aktuellen Sprache. */
export function groupLabel(group: string): string {
  const key = groupKey(group);
  return KNOWN_GROUPS.includes(key) ? String(i18n.t(`commands:groups.${key}`)) : group;
}

function groupRank(group: string): number {
  const i = GROUP_ORDER.indexOf(group);
  return i < 0 ? GROUP_ORDER.length : i;
}

interface Row {
  cmd: CommandDef;
  group: string;
  key: string;
}

/** Baut die angezeigten Zeilen: mit Suchbegriff nach Punktzahl (Gruppen in Trefferreihenfolge), sonst Zuletzt benutzt zuerst. */
export function buildRows(query: string, commands: CommandDef[], recentIds: string[], subList: boolean): Row[] {
  if (query.trim()) {
    const hits = searchCommands(query, commands, 60);
    const order: string[] = [];
    for (const c of hits) {
      const g = groupKey(c.group);
      if (!order.includes(g)) order.push(g);
    }
    return order.flatMap((g) =>
      hits.filter((c) => groupKey(c.group) === g).map((cmd) => ({ cmd, group: g, key: `${g}:${cmd.id}` })),
    );
  }
  const enabled = commands.filter(isEnabled);
  if (subList) return enabled.map((cmd) => ({ cmd, group: groupKey(cmd.group), key: `${cmd.group}:${cmd.id}` }));
  const byId = new Map(enabled.map((c) => [c.id, c]));
  const recent = recentIds.map((id) => byId.get(id)).filter((c): c is CommandDef => Boolean(c));
  const keyed = enabled.map((cmd) => ({ cmd, group: groupKey(cmd.group) }));
  const rest = keyed.sort((a, b) => groupRank(a.group) - groupRank(b.group) || a.group.localeCompare(b.group, 'de'));
  return [
    ...recent.map((cmd) => ({ cmd, group: RECENT_GROUP, key: `recent:${cmd.id}` })),
    ...rest.map(({ cmd, group }) => ({ cmd, group, key: `${group}:${cmd.id}` })),
  ];
}

const useStyles = makeStyles({
  surface: {
    position: 'fixed',
    top: '12vh',
    left: '50%',
    transform: 'translateX(-50%)',
    margin: 0,
    padding: 0,
    width: 'min(640px, calc(100vw - 32px))',
    maxWidth: 'none',
    borderRadius: tokens.borderRadiusXLarge,
    overflow: 'hidden',
    boxShadow: tokens.shadow64,
  },
  searchRow: {
    padding: tokens.spacingHorizontalM,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  input: { width: '100%' },
  subTitle: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalL} 0`,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalXS,
  },
  list: {
    maxHeight: 'min(60vh, 460px)',
    overflowY: 'auto',
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS} ${tokens.spacingVerticalS}`,
  },
  groupLabel: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM} ${tokens.spacingVerticalXXS}`,
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground3,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  option: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalM,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    cursor: 'pointer',
    color: tokens.colorNeutralForeground1,
    position: 'relative',
    transitionProperty: 'background-color',
    transitionDuration: tokens.durationFaster,
  },
  active: {
    backgroundColor: tokens.colorSubtleBackgroundHover,
    '::before': {
      content: '""',
      position: 'absolute',
      left: 0,
      top: '25%',
      bottom: '25%',
      width: '3px',
      borderRadius: tokens.borderRadiusCircular,
      backgroundColor: tokens.colorBrandBackground,
    },
  },
  title: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  kbd: {
    flexShrink: 0,
    fontFamily: tokens.fontFamilyBase,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground2,
    padding: `1px ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderBottomWidth: tokens.strokeWidthThick,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  empty: { padding: tokens.spacingHorizontalXL, textAlign: 'center', color: tokens.colorNeutralForeground3 },
  footer: {
    display: 'flex',
    columnGap: tokens.spacingHorizontalL,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalL}`,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground2,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase100,
  },
});

export function CommandPalette(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  commands: CommandDef[];
  recentIds: string[];
  subTitle?: string;
  onRun: (cmd: CommandDef) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('commands');
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { open, subTitle, commands, recentIds } = props;

  useEffect(() => {
    if (!open) return undefined;
    setQuery('');
    setActive(0);
    // Die Dialog-Fokusverwaltung greift erst nach dem Einblenden; das Suchfeld bekommt den Fokus ausdrücklich.
    const timer = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [open, subTitle]);

  const rows = useMemo(
    () => (open ? buildRows(query, commands, recentIds, Boolean(subTitle)) : []),
    [open, query, commands, recentIds, subTitle],
  );
  const activeIndex = rows.length === 0 ? -1 : Math.min(active, rows.length - 1);
  const activeRow = activeIndex >= 0 ? rows[activeIndex] : undefined;
  const optionId = (i: number) => `${listId}-opt-${i}`;

  useEffect(() => {
    if (activeIndex < 0) return;
    document.getElementById(optionId(activeIndex))?.scrollIntoView({ block: 'nearest' });
    // optionId ist stabil über listId
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, listId]);

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (rows.length) setActive((activeIndex + 1) % rows.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (rows.length) setActive((activeIndex - 1 + rows.length) % rows.length);
    } else if (e.key === 'Home') {
      e.preventDefault();
      setActive(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      setActive(Math.max(0, rows.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeRow) props.onRun(activeRow.cmd);
    }
  };

  const groups: { group: string; items: { row: Row; index: number }[] }[] = [];
  rows.forEach((row, index) => {
    const last = groups[groups.length - 1];
    if (last && last.group === row.group) last.items.push({ row, index });
    else groups.push({ group: row.group, items: [{ row, index }] });
  });

  return (
    <Dialog open={open} onOpenChange={(_e, d) => props.onOpenChange(d.open)}>
      <DialogSurface className={styles.surface} aria-label={t('palette.label')}>
        <div className={styles.searchRow}>
          <Input
            className={styles.input}
            appearance="filled-lighter"
            size="large"
            contentBefore={<Search20Regular />}
            placeholder={subTitle ? t('palette.placeholderSub') : t('palette.placeholder')}
            value={query}
            onChange={(_e, d) => {
              setQuery(d.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            ref={inputRef}
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
            aria-label={t('palette.search')}
            aria-autocomplete="list"
          />
        </div>
        {subTitle ? (
          <div className={styles.subTitle}>
            <ChevronRight16Regular aria-hidden="true" />
            {subTitle}
          </div>
        ) : null}
        {rows.length === 0 ? (
          <div className={styles.empty} role="status">
            {t('palette.empty')}
          </div>
        ) : null}
        <div className={styles.list} role="listbox" id={listId} ref={listRef} aria-label={t('palette.list')}>
          {groups.map((g) => (
            <div role="group" aria-label={groupLabel(g.group)} key={`${g.group}-${g.items[0]?.index ?? 0}`}>
              <div className={styles.groupLabel} aria-hidden="true">
                {groupLabel(g.group)}
              </div>
              {g.items.map(({ row, index }) => (
                <div
                  key={row.key}
                  id={optionId(index)}
                  role="option"
                  aria-selected={index === activeIndex}
                  className={mergeClasses(styles.option, index === activeIndex && styles.active)}
                  onMouseMove={() => {
                    if (index !== activeIndex) setActive(index);
                  }}
                  onClick={() => props.onRun(row.cmd)}
                >
                  <span className={styles.title}>{row.cmd.title}</span>
                  {row.cmd.shortcut ? (
                    <kbd className={styles.kbd}>{row.cmd.shortcut}</kbd>
                  ) : null}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className={styles.footer} aria-hidden="true">
          <span>{t('palette.footerSelect')}</span>
          <span>{t('palette.footerRun')}</span>
          <span>{t('palette.footerClose')}</span>
        </div>
      </DialogSurface>
    </Dialog>
  );
}
