import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup, configure } from '@testing-library/react';
import { FakeEventSource } from './src/test/fakeEventSource';
import { restoreAllMocks } from './src/test/utils';
import { setTokenForTests } from './src/api/client';
import { resetUnsavedForTests } from './src/api/unsaved';
import { resetWindowSessionForTests } from './src/api/session';
import { resetDraftSyncForTests } from './src/pages/Editor/tabs/useDraftSync';
import { i18n, initI18n } from './src/i18n';

// Unter Last (viele parallele jsdom-Worker) brauchen Fluent-Dialoge mehr als die Standard-Sekunde
// bis zum ersten Rendern; findBy*/waitFor warten deshalb bis zu 5 s.
configure({ asyncUtilTimeout: 5000 });

// Browser-Sprache fest auf Deutsch, damit "auto" in jedem Test Deutsch ergibt.
Object.defineProperty(window.navigator, 'language', { value: 'de-DE', configurable: true });
Object.defineProperty(window.navigator, 'languages', { value: ['de-DE', 'de'], configurable: true });

// i18n im Testmodus: ein fehlender Schlüssel wirft einen Fehler und lässt den Test scheitern.
initI18n({ language: 'de', test: true });

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

class ResizeObserverPolyfill {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!('ResizeObserver' in globalThis)) {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverPolyfill;
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

if (!globalThis.crypto) {
  (globalThis as unknown as { crypto: object }).crypto = {};
}
if (!globalThis.crypto.randomUUID) {
  let n = 0;
  (globalThis.crypto as unknown as { randomUUID: () => string }).randomUUID = () => {
    n += 1;
    return `00000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`;
  };
}

(globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;

afterEach(() => {
  cleanup();
  // Nach dem Aushängen: Übergaben des Editors (Autosave) nicht in den nächsten Test tragen.
  resetDraftSyncForTests();
  restoreAllMocks();
  setTokenForTests(null);
  FakeEventSource.reset();
  resetUnsavedForTests();
  resetWindowSessionForTests();
  if (i18n.language !== 'de') void i18n.changeLanguage('de');
  document.documentElement.lang = 'de';
  try {
    sessionStorage.clear();
    localStorage.clear();
  } catch {
    // ignorieren
  }
});
