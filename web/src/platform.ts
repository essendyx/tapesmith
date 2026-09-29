/** Brücke zum App-Fenster (pywebview) mit Rückfall für den normalen Browser. */
import { i18n } from './i18n';

function api(): PywebviewApi | undefined {
  return window.pywebview?.api;
}

export const isAppWindow = (): boolean => api() !== undefined;

export async function pickFolder(title?: string): Promise<string | null> {
  const fn = api()?.pick_folder;
  if (!fn) return null;
  try {
    return (await fn(title)) ?? null;
  } catch {
    return null;
  }
}

export async function openPath(path: string): Promise<boolean> {
  const fn = api()?.open_path;
  if (!fn) return false;
  try {
    return Boolean(await fn(path));
  } catch {
    return false;
  }
}

export async function closeWindow(): Promise<void> {
  const fn = api()?.close_window;
  if (fn) {
    try {
      await fn();
      return;
    } catch {
      // Rückfall unten
    }
  }
  window.close();
}

/**
 * Nur im App-Fenster: Druckdienst bei Bedarf starten und die Oberfläche mit frischer Sitzung
 * (neues Token) auf `route` neu laden (`AppApi.retry` im Fenster-Prozess). `false` im Browser
 * oder wenn die Brücke fehlschlägt.
 */
export async function reconnectService(route: string): Promise<boolean> {
  const fn = api()?.retry;
  if (!fn) return false;
  try {
    await fn(route);
    return true;
  } catch {
    return false;
  }
}

export async function setWindowTitle(title: string): Promise<void> {
  document.title = title;
  const fn = api()?.set_title;
  if (!fn) return;
  try {
    await fn(title);
  } catch {
    // Titel im Browser reicht
  }
}

export async function readClipboardText(): Promise<string> {
  try {
    return (await navigator.clipboard?.readText()) ?? '';
  } catch {
    return '';
  }
}

export async function copyPngToClipboard(b64: string): Promise<boolean> {
  try {
    if (typeof ClipboardItem === 'undefined' || !navigator.clipboard?.write) return false;
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'image/png' });
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    return true;
  } catch {
    return false;
  }
}

/** Datei als Base64 (ohne data:-Präfix). */
export async function readFileAsB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error(i18n.t('common:errors.fileUnreadable')));
    reader.onload = () => {
      const result = String(reader.result ?? '');
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}
