/** Befehlsregister, Palette (Strg+K), Strg+P, Tastenkürzel-Übersicht (? und F1) und die eingebauten Befehle. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { resolveLanguage } from '../i18n';
import { apiGet, apiPatch, apiPost } from '../api/client';
import { fetchTapes, qk, refreshStatus, setCurrentTape, useQueueSnapshot } from '../api/core';
import type { AppInfo, HistoryEntryJson, TemplateSummary } from '../api/types';
import { useErrorText } from '../components/ErrorMessage';
import { useNotify } from '../components/NotifyProvider';
import { usePrint } from '../components/usePrint';
import { isRouteVisible, ROUTES, routeShortcut } from '../routes';
import { useModules } from '../modules';
import { ShortcutsDialog } from '../shell/ShortcutsDialog';
import { StatusDetailDialog } from '../shell/StatusDetailDialog';
import { CommandPalette } from './CommandPalette';
import { CommandRegistry, isEnabled, type CommandDef } from './registry';
import { formatCombo, useShortcut } from './shortcuts';

export type { CommandDef } from './registry';

interface CommandsContextValue {
  registry: CommandRegistry;
  open(): void;
  showList(title: string, commands: CommandDef[]): void;
  run(id: string): boolean;
  paletteOpen: boolean;
  openShortcuts(): void;
}

const CommandsContext = createContext<CommandsContextValue | null>(null);

const MAX_RECENT = 6;

export function CommandProvider(props: { children: ReactNode }): JSX.Element {
  const [registry] = useState(() => new CommandRegistry());
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [subList, setSubList] = useState<{ title: string; commands: CommandDef[] } | null>(null);
  const [recentIds, setRecentIds] = useState<string[]>([]);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const notify = useNotify();
  const errorText = useErrorText();
  const notifyRef = useRef<(err: unknown) => void>(() => undefined);
  notifyRef.current = (err: unknown) => {
    const e = errorText(err);
    notify({ intent: 'error', title: e.title, body: e.message || undefined, hint: e.hint || undefined });
  };

  const version = useSyncExternalStore(
    useCallback((fn: () => void) => registry.subscribe(fn), [registry]),
    () => registry.version,
  );

  const execute = useCallback(
    (cmd: CommandDef) => {
      setRecentIds((prev) => [cmd.id, ...prev.filter((id) => id !== cmd.id)].slice(0, MAX_RECENT));
      try {
        const result = cmd.run();
        if (result && typeof (result as Promise<void>).then === 'function') {
          (result as Promise<void>).catch((err: unknown) => notifyRef.current(err));
        }
      } catch (err) {
        notifyRef.current(err);
      }
    },
    [],
  );

  const run = useCallback(
    (id: string) => {
      const cmd = registry.get(id);
      if (!cmd || !isEnabled(cmd)) return false;
      execute(cmd);
      return true;
    },
    [registry, execute],
  );

  const open = useCallback(() => {
    setSubList(null);
    setPaletteOpen(true);
  }, []);
  const showList = useCallback((title: string, commands: CommandDef[]) => {
    setSubList({ title, commands });
    setPaletteOpen(true);
  }, []);
  const openShortcuts = useCallback(() => {
    setPaletteOpen(false);
    setSubList(null);
    setShortcutsOpen(true);
  }, []);

  const value = useMemo<CommandsContextValue>(
    () => ({ registry, open, showList, run, paletteOpen, openShortcuts }),
    [registry, open, showList, run, paletteOpen, openShortcuts],
  );

  useShortcut('Ctrl+K', open, { allowInInputs: true });
  useShortcut(
    'Ctrl+P',
    () => {
      run('druck.aktuell');
    },
    { allowInInputs: true },
  );
  useShortcut('?', openShortcuts);
  useShortcut('F1', openShortcuts);

  const commands = useMemo(
    () => (subList ? subList.commands : registry.all()),
    // version ändert sich bei jeder (Ab-)Meldung
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subList, registry, version],
  );

  return (
    <CommandsContext.Provider value={value}>
      <BuiltinCommands paletteOpen={paletteOpen} />
      {props.children}
      <CommandPalette
        open={paletteOpen}
        onOpenChange={(open) => {
          setPaletteOpen(open);
          if (!open) setSubList(null);
        }}
        commands={commands}
        recentIds={recentIds}
        subTitle={subList?.title}
        onRun={(cmd) => {
          setPaletteOpen(false);
          setSubList(null);
          execute(cmd);
        }}
      />
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} commands={shortcutsOpen ? registry.all() : []} />
    </CommandsContext.Provider>
  );
}

function useCommandsContext(): CommandsContextValue {
  const ctx = useContext(CommandsContext);
  if (!ctx) throw new Error('useCommands without CommandProvider');
  return ctx;
}

/** Registriert Befehle, solange die Komponente lebt. */
export function useRegisterCommands(commands: CommandDef[], deps: unknown[]): void {
  const { registry } = useCommandsContext();
  const ref = useRef(commands);
  ref.current = commands;
  useEffect(() => {
    // Aufrufe gehen immer an die aktuelle Fassung (Closures bleiben frisch, ohne neu zu registrieren)
    const wrapped = ref.current.map<CommandDef>((c, i) => ({
      ...c,
      run: () => (ref.current[i] ?? c).run(),
      enabled: c.enabled ? () => (ref.current[i]?.enabled ?? c.enabled)?.() ?? true : undefined,
    }));
    return registry.register(wrapped);
    // deps bestimmt der Aufrufer
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [registry, ...deps]);
}

export function useCommands(): { all(): CommandDef[]; run(id: string): boolean; open(): void; openShortcuts(): void } {
  const ctx = useCommandsContext();
  return useMemo(
    () => ({ all: () => ctx.registry.all(), run: ctx.run, open: ctx.open, openShortcuts: ctx.openShortcuts }),
    [ctx],
  );
}

/** Stabile Gruppen-Kennungen der eingebauten Befehle; angezeigt über `commands:groups.<id>`. */
export const COMMAND_GROUPS = {
  navigation: 'navigation',
  print: 'print',
  templates: 'templates',
  printer: 'printer',
  tapes: 'tapes',
  queue: 'queue',
  drives: 'drives',
  settings: 'settings',
  appearance: 'appearance',
  help: 'help',
} as const;

type LanguageValue = AppInfo['language'];
type ThemeValue = AppInfo['theme'];

/** Eingebaute Befehle der Palette (Navigation, Vorlagen, Drucker, Warteschlange, Datenträger, Darstellung). */
function BuiltinCommands(props: { paletteOpen: boolean }): JSX.Element {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const notify = useNotify();
  const print = usePrint();
  const ctx = useCommandsContext();
  const { t, i18n } = useTranslation('commands');
  const language = i18n.language;
  const [statusOpen, setStatusOpen] = useState(false);
  const queue = useQueueSnapshot({ enabled: props.paletteOpen });
  const templates = useQuery({
    queryKey: qk.templates,
    queryFn: ({ signal }) => apiGet<{ templates: TemplateSummary[] }>('/api/v1/templates', signal),
    enabled: props.paletteOpen,
    retry: false,
  });
  const paused = queue.data?.paused ?? false;
  const templateList = templates.data?.templates;
  const modules = useModules();
  const drivesOn = modules.isEnabled('datentraeger');

  const navCommands = useMemo<CommandDef[]>(
    () =>
      ROUTES.filter((r) => isRouteVisible(r, modules)).map((r) => ({
        id: `nav.${r.key}`,
        title: t('builtin.goto', { title: t(r.titleKey) }),
        group: COMMAND_GROUPS.navigation,
        keywords: [r.key, r.title, ...r.keywords],
        shortcut: routeShortcut(r),
        run: () => navigate(r.path),
      })),
    // language: Titel und Kürzel folgen der Sprache
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [navigate, t, language, modules],
  );
  useRegisterCommands(navCommands, [navCommands]);

  const templateCommands = useMemo<CommandDef[]>(
    () =>
      (templateList ?? []).map((tpl) => ({
        id: `vorlage.${tpl.name}`,
        title: t('builtin.template', { name: tpl.name }),
        group: COMMAND_GROUPS.templates,
        keywords: [...tpl.tags, tpl.category].filter(Boolean),
        run: () => navigate(`/vorlagen?vorlage=${encodeURIComponent(tpl.name)}`),
      })),
    [templateList, navigate, t],
  );
  useRegisterCommands(templateCommands, [templateCommands]);

  const printRun = print.run;
  const showList = ctx.showList;
  const openShortcuts = ctx.openShortcuts;
  const fixed = useMemo<CommandDef[]>(() => {
    const setSetting = async (key: 'app.language' | 'app.theme', value: LanguageValue | ThemeValue, title: () => string) => {
      await apiPatch('/api/v1/settings', { changes: { [key]: value } });
      await queryClient.invalidateQueries({ queryKey: qk.app });
      void queryClient.invalidateQueries({ queryKey: qk.settings });
      notify({ intent: 'success', title: title() });
    };
    const languageCommand = (value: LanguageValue, titleKey: string, words: string[]): CommandDef => ({
      id: `sprache.${value}`,
      title: t(titleKey),
      group: COMMAND_GROUPS.appearance,
      keywords: ['sprache', 'language', ...words],
      // Bestätigung schon in der neuen Sprache
      run: () =>
        setSetting('app.language', value, () => String(i18n.getFixedT(resolveLanguage(value), 'commands')('builtin.languageChanged'))),
    });
    const themeCommand = (value: ThemeValue, titleKey: string): CommandDef => ({
      id: `farbschema.${value}`,
      title: t(titleKey),
      group: COMMAND_GROUPS.appearance,
      keywords: ['farbschema', 'theme', 'dark', 'light', 'dunkel', 'hell', 'modus', 'mode'],
      run: () => setSetting('app.theme', value, () => t('builtin.themeChanged')),
    });
    // Befehle des Moduls Datenträger nur, wenn es eingeschaltet ist.
    const drives: CommandDef[] = drivesOn
      ? [
          {
            id: 'vorlage.datentraeger-neu',
            title: t('builtin.driveLabel'),
            group: COMMAND_GROUPS.templates,
            keywords: ['ssd', 'hdd', 'nvme', 'platte', 'disk'],
            run: () => navigate('/vorlagen?vorlage=datentraeger'),
          },
          {
            id: 'datentraeger.ssh',
            title: t('builtin.sshScanner'),
            group: COMMAND_GROUPS.drives,
            keywords: ['ssh', 'server', 'scanner', 'zfs'],
            run: () => navigate('/datentraeger?tab=ssh'),
          },
          {
            id: 'datentraeger.assistent',
            title: t('builtin.driveWizard'),
            group: COMMAND_GROUPS.drives,
            keywords: ['laufwerk', 'usb', 'stick', 'festplatte', 'drive', 'disk'],
            run: () => navigate('/datentraeger?tab=laufwerke'),
          },
        ]
      : [];
    return [
      ...drives,
      {
        id: 'druck.letztes',
        title: t('builtin.reprint'),
        group: COMMAND_GROUPS.print,
        keywords: ['wieder', 'nochmal', 'reprint', 'again'],
        run: async () => {
          const res = await apiGet<{ entries: HistoryEntryJson[] }>('/api/v1/history?limit=1');
          const entry = res.entries[0];
          if (!entry) {
            notify({ intent: 'info', title: t('builtin.nothingPrinted') });
            return;
          }
          await printRun({ kind: 'history', id: entry.id });
        },
      },
      {
        id: 'band.waehlen',
        title: t('builtin.tapeChoose'),
        group: COMMAND_GROUPS.printer,
        keywords: ['band', 'tape', 'rolle', 'roll'],
        run: async () => {
          const data = await queryClient.fetchQuery({ queryKey: qk.tapes, queryFn: ({ signal }) => fetchTapes(signal) });
          showList(
            t('builtin.tapeChoose'),
            data.tapes.map((tape) => ({
              id: `band.${tape.id}`,
              title: tape.id === data.current ? t('builtin.tapeCurrent', { name: tape.name }) : tape.name,
              group: COMMAND_GROUPS.tapes,
              keywords: [tape.id, tape.material],
              run: async () => {
                const next = await setCurrentTape(tape.id);
                queryClient.setQueryData(qk.tapes, next);
                void queryClient.invalidateQueries({ queryKey: qk.app });
                notify({ intent: 'success', title: t('builtin.tapeChosen', { name: tape.name }) });
              },
            })),
          );
        },
      },
      {
        id: 'status.abfragen',
        title: t('builtin.statusQuery'),
        group: COMMAND_GROUPS.printer,
        keywords: ['status', 'drucker', 'akku', 'verbindung', 'printer', 'battery'],
        run: async () => {
          const fresh = await refreshStatus();
          queryClient.setQueryData(qk.status, fresh);
          notify({ intent: fresh.view.role === 'error' ? 'error' : 'info', title: fresh.view.title, body: fresh.view.chip });
        },
      },
      {
        id: 'status.detail',
        title: t('builtin.statusDetail'),
        group: COMMAND_GROUPS.printer,
        keywords: ['status', 'details', 'diagnose', 'diagnostics'],
        run: () => setStatusOpen(true),
      },
      {
        id: 'warteschlange.umschalten',
        title: paused ? t('builtin.queueResume') : t('builtin.queuePause'),
        group: COMMAND_GROUPS.queue,
        keywords: ['queue', 'pause', 'pausieren', 'fortsetzen', 'anhalten', 'resume'],
        run: async () => {
          await apiPost(paused ? '/api/v1/queue/resume' : '/api/v1/queue/pause', {});
          void queryClient.invalidateQueries({ queryKey: qk.queue });
          notify({ intent: 'info', title: paused ? t('builtin.queueResumed') : t('builtin.queuePaused') });
        },
      },
      {
        id: 'einstellungen.oeffnen',
        title: t('builtin.settingsOpen'),
        group: COMMAND_GROUPS.settings,
        keywords: ['optionen', 'konfiguration', 'settings', 'options'],
        shortcut: formatCombo('Ctrl+,'),
        run: () => navigate('/einstellungen'),
      },
      languageCommand('de', 'builtin.languageDe', ['deutsch', 'german']),
      languageCommand('en', 'builtin.languageEn', ['english', 'englisch']),
      languageCommand('auto', 'builtin.languageAuto', ['auto', 'system', 'windows']),
      themeCommand('hell', 'builtin.themeLight'),
      themeCommand('dunkel', 'builtin.themeDark'),
      themeCommand('system', 'builtin.themeSystem'),
      {
        id: 'hilfe.tastenkuerzel',
        title: t('builtin.shortcuts'),
        group: COMMAND_GROUPS.help,
        keywords: ['tastenkürzel', 'kürzel', 'shortcuts', 'keyboard', 'hilfe', 'help', 'tastatur'], // i18n-ignore (Suchbegriffe)
        shortcut: '?',
        run: () => openShortcuts(),
      },
    ];
    // language: Kürzel-Anzeige folgt der Sprache
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, notify, printRun, queryClient, showList, openShortcuts, paused, t, i18n, language, drivesOn]);
  useRegisterCommands(fixed, [fixed]);

  return statusOpen ? <StatusDetailDialog open onOpenChange={setStatusOpen} /> : <></>;
}
