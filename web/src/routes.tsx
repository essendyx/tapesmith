/**
 * Routen der Oberfläche (deutsche Pfade, Reihenfolge = Seitenleiste). Zuerst die Kernapp, danach die
 * Seiten der Module (`module`) und die Homelab-Übersicht (`homelab`, sichtbar, sobald ein
 * Integrationsmodul eingeschaltet ist). Strg+1 bis Strg+8 gehören fest zu den Seiten der Kernapp.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import {
  Box20Filled,
  Box20Regular,
  DataBarVertical20Filled,
  DataBarVertical20Regular,
  DesignIdeas20Filled,
  DesignIdeas20Regular,
  DocumentText20Filled,
  DocumentText20Regular,
  Flash20Filled,
  Flash20Regular,
  Grid20Filled,
  Grid20Regular,
  HardDrive20Filled,
  HardDrive20Regular,
  History20Filled,
  History20Regular,
  QrCode20Filled,
  QrCode20Regular,
  Server20Filled,
  Server20Regular,
  Settings20Filled,
  Settings20Regular,
  ShieldKeyhole20Filled,
  ShieldKeyhole20Regular,
  TaskListLtr20Filled,
  TaskListLtr20Regular,
  type FluentIcon,
} from '@fluentui/react-icons';
import { formatCombo } from './commands/shortcuts';
import { currentLanguage, i18n, type Language } from './i18n';
import { HOMELAB_MODULES, moduleForHomelab, moduleForSidebar, moduleTexts, type ModulesState } from './modules';

export interface RouteDef {
  key: string;
  path: string;
  /** Deutscher Titel (für bestehende Aufrufer); angezeigt wird `t(titleKey)`. */
  title: string;
  /** Übersetzungsschlüssel des Titels, z. B. `shell:routes.schnelldruck`. */
  titleKey: string;
  icon: FluentIcon;
  iconActive: FluentIcon;
  keywords: string[];
  bottom?: boolean;
  /** Seite eines Moduls: nur sichtbar, wenn das Modul eingeschaltet ist. */
  module?: string;
  /** Homelab-Übersicht: sichtbar, sobald ein Integrationsmodul eingeschaltet ist. */
  homelab?: boolean;
  element: LazyExoticComponent<ComponentType>;
}

export const ROUTES: RouteDef[] = [
  {
    key: 'schnelldruck',
    path: '/schnelldruck',
    title: 'Schnelldruck',
    titleKey: 'shell:routes.schnelldruck',
    icon: Flash20Regular,
    iconActive: Flash20Filled,
    keywords: ['text', 'start', 'drucken', 'schnell', 'quick', 'print', 'fast'],
    element: lazy(() => import('./pages/Schnelldruck')),
  },
  {
    key: 'editor',
    path: '/editor',
    title: 'Editor',
    titleKey: 'shell:routes.editor',
    icon: DesignIdeas20Regular,
    iconActive: DesignIdeas20Filled,
    keywords: ['gestalten', 'layout', 'canvas', 'dokument', 'design', 'draw', 'document'],
    element: lazy(() => import('./pages/Editor')),
  },
  {
    key: 'galerie',
    path: '/galerie',
    title: 'Galerie',
    titleKey: 'shell:routes.galerie',
    icon: Grid20Regular,
    iconActive: Grid20Filled,
    keywords: ['beispiele', 'vorlagen', 'katalog', 'gallery', 'examples', 'samples'],
    element: lazy(() => import('./pages/Galerie')),
  },
  {
    key: 'vorlagen',
    path: '/vorlagen',
    title: 'Vorlagen',
    titleKey: 'shell:routes.vorlagen',
    icon: DocumentText20Regular,
    iconActive: DocumentText20Filled,
    keywords: ['template', 'serie', 'import', 'csv', 'templates', 'series', 'batch'],
    element: lazy(() => import('./pages/Vorlagen')),
  },
  {
    key: 'qr',
    path: '/qr',
    title: 'QR-Code',
    titleKey: 'shell:routes.qr',
    icon: QrCode20Regular,
    iconActive: QrCode20Filled,
    keywords: ['qr', 'code', 'wlan', 'wifi', 'visitenkarte', 'url', 'qr code', 'link', 'business card'],
    element: lazy(() => import('./pages/Qr')),
  },
  {
    key: 'verlauf',
    path: '/verlauf',
    title: 'Verlauf',
    titleKey: 'shell:routes.verlauf',
    icon: History20Regular,
    iconActive: History20Filled,
    keywords: ['history', 'nachdruck', 'gedruckt', 'reprint', 'printed', 'log'],
    element: lazy(() => import('./pages/Verlauf')),
  },
  {
    key: 'warteschlange',
    path: '/warteschlange',
    title: 'Warteschlange',
    titleKey: 'shell:routes.warteschlange',
    icon: TaskListLtr20Regular,
    iconActive: TaskListLtr20Filled,
    keywords: ['queue', 'aufträge', 'jobs', 'offline', 'pending', 'retry'], // i18n-ignore (Suchbegriffe)
    element: lazy(() => import('./pages/Warteschlange')),
  },
  {
    key: 'statistik',
    path: '/statistik',
    title: 'Statistik',
    titleKey: 'shell:routes.statistik',
    icon: DataBarVertical20Regular,
    iconActive: DataBarVertical20Filled,
    keywords: ['verbrauch', 'rollen', 'zahlen', 'statistics', 'usage', 'rolls', 'numbers'],
    element: lazy(() => import('./pages/Statistik')),
  },
  {
    key: 'inventar',
    path: '/inventar',
    title: 'Inventar',
    titleKey: 'shell:routes.inventar',
    icon: Box20Regular,
    iconActive: Box20Filled,
    keywords: ['kisten', 'boxen', 'lager', 'verleih', 'inventory', 'boxes', 'storage', 'loan'],
    module: moduleForSidebar('inventar'),
    element: lazy(() => import('./pages/Inventar')),
  },
  {
    key: 'datentraeger',
    path: '/datentraeger',
    title: 'Datenträger', // i18n-ignore (Altfeld, angezeigt wird titleKey)
    titleKey: 'shell:routes.datentraeger',
    icon: HardDrive20Regular,
    iconActive: HardDrive20Filled,
    keywords: ['festplatte', 'laufwerk', 'ssh', 'scanner', 'zfs', 'plattentausch', 'drive', 'disk', 'drives'],
    module: moduleForSidebar('datentraeger'),
    element: lazy(() => import('./pages/Datentraeger')),
  },
  {
    key: 'homelab',
    path: '/homelab',
    title: 'Homelab',
    titleKey: 'shell:routes.homelab',
    icon: Server20Regular,
    iconActive: Server20Filled,
    keywords: ['proxmox', 'paperless', 'asn', 'vault', 'obsidian', 'asset', 'kurzlink', 'kabel', 'netbox', 'batterie', 'wartung', 'kleinanzeigen', 'seriennummer', 'homelab', 'rack', 'server', 'cable', 'battery', 'serial number', 'classifieds'],
    homelab: true,
    element: lazy(() => import('./pages/Homelab')),
  },
  {
    key: 'zugriff',
    path: '/zugriff',
    title: 'Zugriff',
    titleKey: 'shell:routes.zugriff',
    icon: ShieldKeyhole20Regular,
    iconActive: ShieldKeyhole20Filled,
    keywords: ['token', 'lan', 'netz', 'familie', 'mqtt', 'home assistant', 'telegram', 'hotfolder', 'mcp', 'claude', 'access', 'network', 'family', 'tokens'],
    bottom: true,
    element: lazy(() => import('./pages/Zugriff')),
  },
  {
    key: 'einstellungen',
    path: '/einstellungen',
    title: 'Einstellungen', // i18n-ignore (Altfeld, angezeigt wird titleKey)
    titleKey: 'shell:routes.einstellungen',
    icon: Settings20Regular,
    iconActive: Settings20Filled,
    keywords: ['optionen', 'konfiguration', 'drucker', 'band', 'kalibrierung', 'settings', 'options', 'printer', 'tape', 'calibration', 'language', 'theme'],
    bottom: true,
    element: lazy(() => import('./pages/Einstellungen')),
  },
];

/** Seiten außerhalb der Seitenleiste. */
export const KOMPAKT_ELEMENT = lazy(() => import('./pages/Kompakt'));
export const AKTION_ELEMENT = lazy(() => import('./pages/Aktion'));

/** Deutsche Titel der Seiten außerhalb der Seitenleiste (für bestehende Aufrufer). */
export const EXTRA_TITLES: Record<string, string> = {
  '/kompakt': 'Kompakt',
  '/aktion': 'Aktion',
};

const EXTRA_TITLE_KEYS: Record<string, string> = {
  '/kompakt': 'shell:routes.kompakt',
  '/aktion': 'shell:routes.aktion',
};

/** Ob eine Route bei diesen eingeschalteten Modulen erscheint (Seitenleiste, Befehlspalette). */
export function isRouteVisible(route: RouteDef, modules: ModulesState): boolean {
  if (route.module) return modules.isEnabled(route.module);
  if (route.homelab) return HOMELAB_MODULES.some((m) => modules.isEnabled(m.id));
  return true;
}

/** Seiten der Kernapp in der Seitenleiste oben (feste Tastenkürzel Strg+1 bis Strg+8). */
export const CORE_TOP_ROUTES: readonly RouteDef[] = ROUTES.filter((r) => !r.bottom && !r.module && !r.homelab);

export function findRoute(pathname: string): RouteDef | undefined {
  return ROUTES.find((r) => pathname === r.path || pathname.startsWith(`${r.path}/`));
}

/** Tastenkürzel einer Seite in der Anzeige-Form („Strg+1“ bzw. „Ctrl+1“). */
export function routeShortcut(route: RouteDef, lang: Language = currentLanguage()): string | undefined {
  const combo = routeCombo(route);
  return combo ? formatCombo(combo, lang) : undefined;
}

/** Tastenkürzel einer Seite in der Form von `useShortcut` ("Ctrl+1"). */
export function routeCombo(route: RouteDef): string | undefined {
  if (route.key === 'einstellungen') return 'Ctrl+,';
  const index = CORE_TOP_ROUTES.indexOf(route);
  return index >= 0 && index < 9 ? `Ctrl+${index + 1}` : undefined;
}

/** Seitentitel in der aktuellen Sprache. */
export function routeTitle(pathname: string): string {
  const route = findRoute(pathname);
  const key = route?.titleKey ?? EXTRA_TITLE_KEYS[pathname] ?? 'shell:appName';
  return String(i18n.t(key));
}

export interface Crumb {
  label: string;
  path: string;
}

/** Pfad für die Kopfzeile: „Homelab › Proxmox“ für Unterseiten, sonst nur der Seitenname. */
export function routeBreadcrumb(pathname: string): Crumb[] {
  const route = findRoute(pathname);
  if (!route) return [{ label: routeTitle(pathname), path: pathname }];
  const crumbs: Crumb[] = [{ label: String(i18n.t(route.titleKey)), path: route.path }];
  if (route.key === 'homelab') {
    const slug = pathname.slice(route.path.length + 1).split('/')[0] ?? '';
    const module = moduleForHomelab(slug);
    if (module) crumbs.push({ label: moduleTexts(module).name, path: `${route.path}/${slug}` });
  }
  return crumbs;
}
