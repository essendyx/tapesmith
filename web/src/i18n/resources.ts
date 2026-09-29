/**
 * Übersetzungen der Web-Oberfläche, automatisch aus `web/src/locales/<sprache>/<namespace>.json`
 * geladen. Ein neuer Namespace braucht nur die beiden JSON-Dateien, keine Änderung hier.
 */
import type { Resource, ResourceLanguage } from 'i18next';

const modules = import.meta.glob('../locales/*/*.json', { eager: true, import: 'default' }) as Record<
  string,
  Record<string, unknown>
>;

const PATH = /\/locales\/([^/]+)\/([^/]+)\.json$/;

function collect(): { resources: Resource; namespaces: string[] } {
  const resources: Resource = {};
  const ns = new Set<string>();
  for (const [path, content] of Object.entries(modules)) {
    const m = PATH.exec(path);
    if (!m?.[1] || !m[2]) continue;
    const lang = m[1];
    const name = m[2];
    const bucket: ResourceLanguage = resources[lang] ?? {};
    bucket[name] = content;
    resources[lang] = bucket;
    ns.add(name);
  }
  return { resources, namespaces: [...ns].sort() };
}

const collected = collect();

export const resources: Resource = collected.resources;
export const namespaces: string[] = collected.namespaces;
