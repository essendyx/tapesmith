/**
 * Seite Einstellungen. Oben die sichtbaren Einstellungen (Drucker, Band, Kalibrierung, Bildschirm,
 * die sichtbaren Felder aus dem Server-Schema, Module und ihre Einstellungskarten, Updates,
 * Sicherung, Windows-Integration, Zugriff, Hilfe und Diagnose), am Ende der eingeklappte Abschnitt
 * „Erweitert“ mit den selten gebrauchten Einstellungen. Einstellungen nur für config.json liefert der
 * Dienst gar nicht erst aus (siehe Handbuch).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, makeStyles, Spinner, tokens } from '@fluentui/react-components';
import { ShieldKeyhole20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { translateOr } from '../../i18n';
import { PageHeader } from '../../components/PageHeader';
import { Section } from '../../components/Section';
import { registerUnsaved } from '../../api/unsaved';
import type { SettingsSection } from '../../api/types';
import { moduleTexts, useModules } from '../../modules';
import { useSettings, useSettingsPorts, useTemplatesQuiet } from './api';
import { SettingsEditContext } from './context';
import { useSettingsEditor } from './useSettingsEditor';
import { GenericSectionCard } from './GenericSectionCard';
import { SectionNav, SettingsSearchBox, type NavItem } from './SectionNav';
import { useActiveSection } from './useActiveSection';
import { useLeaveGuard } from './useLeaveGuard';
import { AdvancedGroup } from './AdvancedGroup';
import {
  ADVANCED_ID,
  INTEGRATION_ADVANCED_ID,
  LEGACY_TARGETS,
  MODULES_CARD_ID,
  PLAUSI_ID,
  SUPPORT_CARD_ID,
  advancedCardId,
  isAdvancedTarget,
  moduleCardId,
  modulesWithSettings,
  readAdvancedOpen,
  writeAdvancedOpen,
} from './sectionIds';
import { ConnectionCard } from './cards/ConnectionCard';
import { TapeRollCard } from './cards/TapeRollCard';
import { CalibrationCard } from './cards/CalibrationCard';
import { ScreenCard } from './cards/ScreenCard';
import { IntegrationCard } from './cards/IntegrationCard';
import { BackupCard } from './cards/BackupCard';
import { ConfigCodeCard } from './cards/ConfigCodeCard';
import { UpdateCard } from './cards/UpdateCard';
import { SupportCard } from './cards/SupportCard';
import { SECRETS_CARD_ID, SecretsCard } from './cards/SecretsCard';
import { ModulesCard } from './modules/ModulesCard';
import { ModuleSettingsCards } from './modules/ModuleSettingsCards';
import { HomelabSettingsCard } from './modules/HomelabSettingsCard';
import { useHomelabSettings } from '../HomelabEinstellungen/api';

/** Abschnitte mit eigener Karte (nicht als generische Karte oben). */
const UPDATES_ID = 'updates';
const UPDATES_FIELDS_ID = 'updates-felder';
const BACKUP_ID = 'sicherung';
const INTEGRATION_ID = 'integration';
const ACCESS_ID = 'zugriff';
const OWN_CARD_SECTIONS = new Set(['verbindung', UPDATES_ID, BACKUP_ID]);
/** Abschnitte, deren erweiterte Felder (Ordner) zusammen in der Karte „Ordner und Archiv“ stehen. */
const FOLDER_SECTIONS = ['sicherung', 'vorlagen', 'archiv'];
const FOLDERS_ID = 'ordner';

const useStyles = makeStyles({
  layout: { display: 'flex', columnGap: tokens.spacingHorizontalXXL, alignItems: 'flex-start' },
  cards: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, minWidth: 0, flex: '1 1 auto' },
});

function scrollToId(id: string): boolean {
  const el = document.getElementById(id);
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return el !== null;
}

/** Scrollt zur Karte `id` und setzt den Fokus auf ihre Überschrift (Deep-Link `?abschnitt=`). */
function focusSectionHeading(id: string): boolean {
  const container = document.getElementById(id);
  if (!container) return false;
  container.scrollIntoView({ block: 'start' });
  const heading = /^H[1-3]$/.test(container.tagName) ? container : container.querySelector<HTMLElement>('h1, h2, h3');
  if (!heading) return true;
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
  heading.focus({ preventScroll: true });
  return true;
}

/** Wie lange der Deep-Link die Karte oben hält, während darüber Karten nachladen und wachsen. */
export const FOLLOW_SECTION_MS = 4000;

/**
 * Springt zur Karte `id`, sobald sie im DOM steht, und hält sie oben, solange die Seite noch
 * wächst (nachladende Karten darüber schoben sie sonst aus dem Bild). Hört auf,
 * sobald der Nutzer selbst scrollt, tippt oder klickt, spätestens nach FOLLOW_SECTION_MS.
 */
function followSection(id: string): () => void {
  let focused = false;
  let stopped = false;
  const align = () => {
    if (stopped) return;
    if (!focused) {
      focused = focusSectionHeading(id);
      return;
    }
    document.getElementById(id)?.scrollIntoView({ block: 'start' });
  };
  const observer = new MutationObserver(align);
  observer.observe(document.body, { childList: true, subtree: true });
  const userEvents = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    observer.disconnect();
    window.clearTimeout(timer);
    for (const name of userEvents) window.removeEventListener(name, stop, true);
  };
  for (const name of userEvents) window.addEventListener(name, stop, true);
  const timer = window.setTimeout(stop, FOLLOW_SECTION_MS);
  align();
  return stop;
}

/** Verweis-Karte zur Seite Zugriff: Tokens, LAN, Familie, MCP, Hotfolder, MQTT, Telegram. */
function AccessLinkCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const navigate = useNavigate();
  return (
    <div id={ACCESS_ID}>
      <Section
        title={t('access.title')}
        description={t('access.description')}
        actions={
          <Button appearance="secondary" icon={<ShieldKeyhole20Regular />} onClick={() => navigate('/zugriff')}>
            {t('access.open')}
          </Button>
        }
      />
    </div>
  );
}

/** Nur die Felder einer Einordnung (Felder älterer Antworten ohne Angabe gelten als sichtbar). */
function withVisibility(section: SettingsSection, visibility: 'sichtbar' | 'erweitert'): SettingsSection {
  return { ...section, fields: section.fields.filter((f) => (f.visibility ?? 'sichtbar') === visibility) };
}

/** Karte „Plausibilitätsprüfung“ (homelab.json, gilt für alle Vorlagen) unter „Erweitert“. */
function PlausiCard(): JSX.Element {
  const { t } = useTranslation('homelabEinstellungen');
  const homelab = useHomelabSettings();
  return (
    <HomelabSettingsCard
      id={PLAUSI_ID}
      title={t('plausi.title')}
      description={t('plausi.description')}
      sections={['plausi']}
      services={[]}
      settings={homelab.data?.settings}
    />
  );
}

export default function EinstellungenPage(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const settings = useSettings();
  const ports = useSettingsPorts();
  const templates = useTemplatesQuiet();
  const editor = useSettingsEditor();
  const modules = useModules();
  const [search, setSearch] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(readAdvancedOpen);
  useLeaveGuard(Object.keys(editor.pending).length > 0);

  const sections = useMemo(() => settings.data?.sections ?? [], [settings.data]);

  // Sprungziele nur einmal je Wert anspringen: sonst zöge jedes Neuladen der Einstellungen (etwa nach
  // dem Speichern einer anderen Karte) Ansicht und Fokus zurück zur Zielkarte.
  const handledHash = useRef<string | null>(null);
  const handledSection = useRef<string | null>(null);

  useEffect(() => {
    const id = location.hash.replace(/^#/, '');
    if (!id) handledHash.current = null;
    if (!id || handledHash.current === id) return;
    if (isAdvancedTarget(id)) setAdvancedOpen(true);
    // Erst versuchen, wenn die Karten (generisch aus dem Schema) tatsächlich im DOM stehen.
    if (scrollToId(id)) handledHash.current = id;
  }, [location.hash, settings.data]);

  useEffect(() => {
    const raw = searchParams.get('abschnitt');
    if (!raw) {
      handledSection.current = null;
      return;
    }
    const id = LEGACY_TARGETS[raw] ?? raw;
    if (handledSection.current === id) return;
    handledSection.current = id;
    // Ziel im eingeklappten Abschnitt: öffnen (ohne den gemerkten Zustand zu ändern).
    if (isAdvancedTarget(id)) setAdvancedOpen(true);
    const stop = followSection(id);
    return () => {
      stop();
      handledSection.current = null;
    };
  }, [searchParams]);

  // Zählt Karten mit ungespeicherten generischen Feldern, solange die Seite lebt.
  useEffect(
    () =>
      registerUnsaved('einstellungen', () => {
        const changedSections = new Set<string>();
        for (const key of Object.keys(editor.pending)) {
          const owner = sections.find((s) => s.fields.some((f) => f.key === key));
          if (owner) changedSections.add(owner.id);
        }
        return changedSections.size;
      }),
    [editor.pending, sections],
  );

  const toggleAdvanced = (open: boolean) => {
    setAdvancedOpen(open);
    writeAdvancedOpen(open);
  };

  const coreSections = useMemo(() => sections.filter((s) => !s.module), [sections]);
  const visibleSections = useMemo(
    () =>
      coreSections
        .filter((s) => !OWN_CARD_SECTIONS.has(s.id))
        .map((s) => withVisibility(s, 'sichtbar'))
        .filter((s) => s.fields.length > 0),
    [coreSections],
  );
  const advancedSections = useMemo(() => {
    const all = coreSections.map((s) => withVisibility(s, 'erweitert')).filter((s) => s.fields.length > 0);
    // Einzelne Ordnerfelder (Sicherung, Vorlagen, Archiv) teilen sich eine Karte „Ordner und Archiv“.
    const folders = all.filter((s) => FOLDER_SECTIONS.includes(s.id));
    const rest = all.filter((s) => !FOLDER_SECTIONS.includes(s.id));
    if (!folders.length) return rest;
    const merged: SettingsSection = { id: FOLDERS_ID, title: t('sectionsAdvanced.ordner'), fields: folders.flatMap((s) => s.fields) };
    const at = all.findIndex((s) => FOLDER_SECTIONS.includes(s.id));
    return [...rest.slice(0, at), merged, ...rest.slice(at)];
  }, [coreSections, t]);
  const updatesSection = useMemo(() => {
    const section = coreSections.find((s) => s.id === UPDATES_ID);
    return section ? withVisibility(section, 'sichtbar') : undefined;
  }, [coreSections]);
  const backupSection = useMemo(() => {
    const section = coreSections.find((s) => s.id === BACKUP_ID);
    return section ? withVisibility(section, 'sichtbar') : undefined;
  }, [coreSections]);
  const moduleCards = modulesWithSettings(modules);
  const searching = search.trim() !== '';

  const navItems: NavItem[] = useMemo(
    () => [
      { id: 'verbindung', title: t('nav.connection') },
      { id: 'band', title: t('nav.tape') },
      { id: 'kalibrierung', title: t('nav.calibration') },
      { id: 'bildschirm', title: t('nav.screen') },
      ...visibleSections.map((s) => ({ id: s.id, title: translateOr(`einstellungen:sections.${s.id}`, s.title) })),
      { id: MODULES_CARD_ID, title: t('nav.modules') },
      ...moduleCards.map((m) => ({ id: moduleCardId(m.id), title: moduleTexts(m.id).name, indent: true })),
      { id: UPDATES_ID, title: t('nav.updates') },
      { id: BACKUP_ID, title: t('nav.backup') },
      { id: INTEGRATION_ID, title: t('nav.integration') },
      { id: SECRETS_CARD_ID, title: t('nav.tokens') },
      { id: ACCESS_ID, title: t('nav.access') },
      { id: SUPPORT_CARD_ID, title: t('nav.support') },
      { id: ADVANCED_ID, title: t('nav.advanced') },
    ],
    // moduleCards ändert sich mit `modules` (stabil je Zustand)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleSections, modules, t],
  );
  const activeId = useActiveSection(navItems);

  return (
    <SettingsEditContext.Provider value={editor}>
      <PageHeader
        title={t('title')}
        subtitle={settings.data?.config_path}
        actions={<SettingsSearchBox value={search} onChange={setSearch} />}
      />
      <div className={styles.layout}>
        <SectionNav items={navItems} activeId={activeId} onJump={scrollToId} />
        <div className={styles.cards}>
          <ConnectionCard />
          <TapeRollCard />
          <CalibrationCard />
          <ScreenCard />

          {settings.isLoading ? <Spinner label={t('loading')} /> : null}
          {visibleSections.map((section) => (
            <GenericSectionCard
              key={section.id}
              section={section}
              searchTerm={search}
              ports={ports.data?.transports}
              templates={templates.data?.templates}
            />
          ))}

          <ModulesCard />
          <ModuleSettingsCards modules={modules} sections={sections} searchTerm={search} />

          <UpdateCard />
          {updatesSection && updatesSection.fields.length > 0 ? (
            <GenericSectionCard
              section={updatesSection}
              searchTerm={search}
              domId={UPDATES_FIELDS_ID}
              titleOverride={t('sections.updatesFields')}
            />
          ) : null}
          <BackupCard section={backupSection} />
          <IntegrationCard id={INTEGRATION_ID} parts={['autostart']} />
          <SecretsCard />
          <AccessLinkCard />
          <SupportCard />

          <AdvancedGroup open={advancedOpen || searching} onToggle={toggleAdvanced}>
            {advancedSections.map((section) => (
              <GenericSectionCard
                key={section.id}
                section={section}
                searchTerm={search}
                domId={advancedCardId(section.id)}
                titleOverride={translateOr(`einstellungen:sectionsAdvanced.${section.id}`, section.title)}
                ports={ports.data?.transports}
                templates={templates.data?.templates}
              />
            ))}
            <IntegrationCard
              id={INTEGRATION_ADVANCED_ID}
              parts={['context', 'uri']}
              title={t('integration.advancedTitle')}
              hint={t('integration.hint')}
            />
            <ConfigCodeCard />
            <PlausiCard />
          </AdvancedGroup>
        </div>
      </div>
    </SettingsEditContext.Provider>
  );
}
