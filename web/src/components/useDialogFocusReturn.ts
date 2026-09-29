/**
 * Gibt den Fokus beim Schließen eines Dialogs an das Element zurück, das beim Öffnen fokussiert
 * war („Dialoge geben den Fokus beim Schließen an den Auslöser zurück“).
 *
 * Nötig für Dialoge, die über lokalen Zustand statt `DialogTrigger` geöffnet werden: dann gibt
 * Fluent den Fokus nicht selbst zurück, und Tabsters eigene Wiederherstellung verlässt sich auf
 * echtes Fokus-Timing, das jsdom nicht zuverlässig nachbildet. Gemeinsamer Baustein für
 * die zuvor je Seite kopierten Fassungen (Assets, Familie, Kleinanzeigen, Paperless, Vault,
 * Zugriff), die Tastenkürzel-Übersicht und den Bestätigungsdialog.
 */
import { useEffect, useRef } from 'react';

export function useDialogFocusReturn(open: boolean): void {
  const returnTo = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);

  // Auslöser beim Rendern merken: die Effekte des Dialogs laufen vor unseren und verschieben den
  // Fokus schon in den Dialog.
  if (open && !wasOpen.current) {
    const active = document.activeElement;
    returnTo.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }
  wasOpen.current = open;

  useEffect(() => {
    if (!open) return undefined;
    return () => {
      const target = returnTo.current;
      returnTo.current = null;
      if (target) setTimeout(() => target.isConnected && target.focus(), 0);
    };
  }, [open]);
}
