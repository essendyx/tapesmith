/**
 * Tastenkürzel-Übersicht: feste Kürzel aus `shortcutCatalog`, dazu die gerade registrierten
 * Kürzel mit Beschreibung (`useShortcut(..., { description })`) und Befehle mit Kürzel. Suche,
 * Gruppen als Tabellen, Kürzel als `kbd`. Öffnet mit `?`/`F1` oder dem Knopf in der Kopfzeile.
 */
import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import {
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
import { Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { fold } from '../commands/fuzzy';
import type { CommandDef } from '../commands/registry';
import { CATALOG_GROUPS, SHORTCUT_CATALOG, type CatalogEntry } from '../commands/shortcutCatalog';
import { formatCombo, listRegisteredShortcuts, subscribeShortcuts } from '../commands/shortcuts';
import { useDialogFocusReturn } from '../components/useDialogFocusReturn';
import { currentLanguage } from '../i18n';

const useStyles = makeStyles({
  surface: { maxWidth: '680px', width: 'min(680px, calc(100vw - 32px))', borderRadius: tokens.borderRadiusXLarge },
  titleRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', columnGap: tokens.spacingHorizontalM },
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, maxHeight: '60vh', overflowY: 'auto' },
  groupTitle: {
    margin: `0 0 ${tokens.spacingVerticalXS}`,
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground2,
  },
  table: { width: '100%', borderCollapse: 'collapse' },
  row: { borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke3}` },
  keysCell: {
    width: '42%',
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalS} ${tokens.spacingVerticalS} 0`,
    verticalAlign: 'top',
  },
  descCell: { padding: `${tokens.spacingVerticalS} 0`, color: tokens.colorNeutralForeground1, verticalAlign: 'top' },
  keys: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalXS, rowGap: tokens.spacingVerticalXXS },
  kbd: {
    fontFamily: tokens.fontFamilyBase,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    padding: `1px ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderBottomWidth: tokens.strokeWidthThick,
    backgroundColor: tokens.colorNeutralBackground2,
    whiteSpace: 'nowrap',
  },
  empty: { color: tokens.colorNeutralForeground3, textAlign: 'center', padding: tokens.spacingVerticalL },
  srOnly: {
    position: 'absolute',
    width: '1px',
    height: '1px',
    overflow: 'hidden',
    clip: 'rect(0 0 0 0)',
    whiteSpace: 'nowrap',
  },
});

export interface ShortcutRow {
  key: string;
  keys: string[];
  description: string;
}

export interface ShortcutGroup {
  id: string;
  title: string;
  rows: ShortcutRow[];
}

function catalogKeys(entry: CatalogEntry, t: (key: string, opts?: Record<string, unknown>) => string): string[] {
  const lang = currentLanguage();
  if (entry.keysLabel === 'digits') {
    return [t('shortcuts.keys.digits', { mod: formatCombo('Ctrl+X', lang).split('+')[0] })];
  }
  if (entry.keysLabel) return [t(`shortcuts.keys.${entry.keysLabel}`)];
  return entry.combos.map((c) => formatCombo(c, lang));
}

/** Alle Gruppen der Übersicht (ohne Suche). */
export function useShortcutGroups(commands: CommandDef[]): ShortcutGroup[] {
  const { t } = useTranslation('commands');
  const registered = useSyncExternalStore(subscribeShortcuts, listRegisteredShortcuts);
  return useMemo(() => {
    const tt = (key: string, opts?: Record<string, unknown>) => String(t(key, opts));
    const lang = currentLanguage();
    const groups: ShortcutGroup[] = CATALOG_GROUPS.map((g) => ({
      id: g,
      title: tt(`shortcuts.groups.${g}`),
      rows: SHORTCUT_CATALOG.filter((e) => e.group === g).map((e) => ({
        key: `catalog:${e.id}`,
        keys: catalogKeys(e, tt),
        description: tt(`shortcuts.items.${e.description}`),
      })),
    }));
    const seen = new Set(groups.flatMap((g) => g.rows.map((r) => `${r.keys.join('|')}:${r.description}`)));
    const byGroup = new Map<string, ShortcutRow[]>();
    for (const r of registered) {
      const row = { key: `reg:${r.id}`, keys: [formatCombo(r.combo, lang)], description: r.description };
      const sig = `${row.keys.join('|')}:${row.description}`;
      if (seen.has(sig)) continue;
      seen.add(sig);
      const title = r.group ?? tt('shortcuts.groups.page');
      byGroup.set(title, [...(byGroup.get(title) ?? []), row]);
    }
    for (const [title, rows] of byGroup) groups.push({ id: `reg:${title}`, title, rows });
    const commandRows = commands
      .filter((c) => c.shortcut)
      .map((c) => ({ key: `cmd:${c.id}`, keys: [c.shortcut ?? ''], description: c.title }))
      .filter((r) => !seen.has(`${r.keys.join('|')}:${r.description}`));
    if (commandRows.length) groups.push({ id: 'commands', title: tt('shortcuts.groups.commands'), rows: commandRows });
    return groups;
  }, [t, registered, commands]);
}

/** Filtert nach Beschreibung, Tasten oder Gruppenname (ohne Groß-/Kleinschreibung und Umlaute). */
export function filterShortcutGroups(groups: ShortcutGroup[], query: string): ShortcutGroup[] {
  const q = fold(query.trim());
  if (!q) return groups;
  return groups
    .map((g) => {
      if (fold(g.title).includes(q)) return g;
      return { ...g, rows: g.rows.filter((r) => fold(`${r.description} ${r.keys.join(' ')}`).includes(q)) };
    })
    .filter((g) => g.rows.length > 0);
}

export function ShortcutsDialog(props: { open: boolean; onOpenChange: (open: boolean) => void; commands: CommandDef[] }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('commands');
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const headingBase = useId();
  const groups = useShortcutGroups(props.commands);
  const visible = filterShortcutGroups(groups, query);
  const { open } = props;

  // Fokus beim Schließen zurück zum Auslöser (gemeinsamer Baustein).
  useDialogFocusReturn(open);

  useEffect(() => {
    if (!open) return undefined;
    setQuery('');
    const timer = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(_e, d) => props.onOpenChange(d.open)}>
      <DialogSurface className={styles.surface} aria-describedby={undefined}>
        <DialogBody>
          <DialogTitle>
            {t('shortcuts.title')}
          </DialogTitle>
          <DialogContent className={styles.content}>
            <Input
              ref={inputRef}
              value={query}
              onChange={(_e, d) => setQuery(d.value)}
              contentBefore={<Search20Regular />}
              placeholder={t('shortcuts.searchPlaceholder')}
              aria-label={t('shortcuts.search')}
              type="search"
            />
            {visible.length === 0 ? (
              <div className={styles.empty} role="status">
                {t('shortcuts.empty')}
              </div>
            ) : null}
            {visible.map((g, gi) => {
              const headingId = `${headingBase}-g${gi}`;
              return (
                <section key={g.id} aria-labelledby={headingId}>
                  <h3 id={headingId} className={styles.groupTitle}>
                    {g.title}
                  </h3>
                  <table className={styles.table} role="table" aria-label={g.title}>
                    <thead className={styles.srOnly}>
                      <tr>
                        <th scope="col">{t('shortcuts.columnKeys')}</th>
                        <th scope="col">{t('shortcuts.columnAction')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.rows.map((r) => (
                        <tr key={r.key} className={styles.row}>
                          <td className={styles.keysCell}>
                            <span className={styles.keys}>
                              {r.keys.map((k) => (
                                <kbd key={k} className={styles.kbd}>
                                  {k}
                                </kbd>
                              ))}
                            </span>
                          </td>
                          <td className={styles.descCell}>{r.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              );
            })}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={() => props.onOpenChange(false)}>
              {t('shortcuts.close')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
