/**
 * Module der Oberfläche: Beschreibung aus `registry.json` (erzeugt aus dem Python-Register
 * `tapesmith.modules`, ein Test prüft die Übereinstimmung) und der Zustand aus `AppInfo.modules`.
 * Ausgeschaltete Module erscheinen nirgends: nicht in der Seitenleiste, der Befehlspalette, der
 * Homelab-Übersicht und den Einstellungen.
 */
import { useMemo } from 'react';
import { useAppInfo } from '../api/core';
import { currentLanguage, type Language } from '../i18n';
import registry from './registry.json';

export interface ModuleTexts {
  name: string;
  description: string;
  example: string;
  requires?: string;
}

export interface ModuleDef {
  id: string;
  kind: 'werkzeug' | 'integration';
  icon: string;
  pages: string[];
  nav: { area: 'sidebar' | 'homelab'; key: string };
  api: string[];
  cli: string[];
  templates: string[];
  categories: string[];
  settings: string[];
  integrations: string[];
  /** Die Seite braucht einen eingerichteten Dienst (sonst Weg zu den Einstellungen). */
  setup: boolean;
  texts: Record<Language, ModuleTexts>;
}

export const MODULES: readonly ModuleDef[] = (registry as { modules: ModuleDef[] }).modules;
export const MODULE_IDS: readonly string[] = MODULES.map((m) => m.id);

export function moduleDef(id: string): ModuleDef | undefined {
  return MODULES.find((m) => m.id === id);
}

export function moduleTexts(id: string, lang: Language = currentLanguage()): ModuleTexts {
  const def = moduleDef(id);
  if (!def) return { name: id, description: '', example: '' };
  return def.texts[lang] ?? def.texts.de;
}

function matches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/** Modul, zu dem eine Seite gehört (z. B. `/homelab/proxmox` -> `proxmox`), sonst undefined. */
export function moduleForPage(pathname: string): string | undefined {
  return MODULES.find((m) => m.pages.some((p) => matches(pathname, p)))?.id;
}

/** Modul eines Eintrags der Seitenleiste (`sidebar:<schlüssel>`). */
export function moduleForSidebar(routeKey: string): string | undefined {
  return MODULES.find((m) => m.nav.area === 'sidebar' && m.nav.key === routeKey)?.id;
}

/** Modul einer Unterseite der Homelab-Übersicht (`homelab:<unterseite>`). */
export function moduleForHomelab(slug: string): string | undefined {
  return MODULES.find((m) => m.nav.area === 'homelab' && m.nav.key === slug)?.id;
}

/** Integrationsmodule mit Kachel in der Homelab-Übersicht, in Register-Reihenfolge. */
export const HOMELAB_MODULES: readonly ModuleDef[] = MODULES.filter((m) => m.nav.area === 'homelab');

export interface ModulesState {
  /** Eingeschaltete Module; solange `AppInfo` lädt, leer (nichts aufblitzen lassen). */
  enabled: ReadonlySet<string>;
  loaded: boolean;
  isEnabled(id: string): boolean;
}

export function modulesState(ids: readonly string[] | undefined): ModulesState {
  const enabled = new Set(ids ?? []);
  return { enabled, loaded: ids !== undefined, isEnabled: (id) => enabled.has(id) };
}

/** Eingeschaltete Module aus `AppInfo` (folgt Änderungen ohne Neustart über das Ereignis `config`). */
export function useModules(): ModulesState {
  const app = useAppInfo();
  const ids = app.data?.modules;
  const key = ids === undefined ? null : ids.join(',');
  return useMemo(() => modulesState(key === null ? undefined : key === '' ? [] : key.split(',')), [key]);
}
