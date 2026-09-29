import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GLOBAL_STYLES, ThemeProvider, buildTheme } from './ThemeProvider';
import { setTokenForTests } from '../api/client';
import type { AppInfo } from '../api/types';
import { fixtures, mockApi } from '../test/utils';
import { resolveDark } from './useSystemDark';

function mockDark(dark: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: dark && query.includes('dark'),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}

function renderTheme() {
  setTokenForTests(null);
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <span>Inhalt</span>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function renderWithSetting(theme: AppInfo['theme']) {
  setTokenForTests('tok');
  mockApi({ 'GET /api/v1/app': () => ({ ...fixtures.appInfo, theme }) });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <span>Inhalt</span>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe('ThemeProvider', () => {
  it('nutzt bei dunklem System das dunkle Theme', () => {
    mockDark(true);
    const { container } = renderTheme();
    expect(container.querySelector('[data-theme="dark"]')).not.toBeNull();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('nutzt bei hellem System das helle Theme', () => {
    mockDark(false);
    const { container } = renderTheme();
    expect(container.querySelector('[data-theme="light"]')).not.toBeNull();
  });

  it('Einstellung dunkel gewinnt gegen helles System', async () => {
    mockDark(false);
    const { container } = renderWithSetting('dunkel');
    await waitFor(() => expect(container.querySelector('[data-theme="dark"]')).not.toBeNull());
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('Einstellung hell gewinnt gegen dunkles System', async () => {
    mockDark(true);
    const { container } = renderWithSetting('hell');
    await waitFor(() => expect(container.querySelector('[data-theme="light"]')).not.toBeNull());
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('Einstellung system folgt matchMedia', async () => {
    mockDark(true);
    const { container } = renderWithSetting('system');
    await waitFor(() => expect(container.querySelector('[data-theme="dark"]')).not.toBeNull());
  });

  it('resolveDark', () => {
    expect(resolveDark('dunkel', false)).toBe(true);
    expect(resolveDark('hell', true)).toBe(false);
    expect(resolveDark('system', true)).toBe(true);
    expect(resolveDark(undefined, false)).toBe(false);
  });

  it('helle Akzente bekommen lesbare Markenfarben', () => {
    const light = buildTheme('#ffb900', false);
    expect(light.colorBrandForeground1).not.toBe('#ffb900');
    expect(light.colorNeutralForegroundOnBrand).toBe('#ffffff');
    expect(light.colorBrandBackground).not.toBe('#ffb900');
  });

  it('dunkles und helles Theme unterscheiden sich im Hintergrund, Markenfarbe aus Stufe 110', () => {
    const light = buildTheme('#0078d4', false);
    const dark = buildTheme('#0078d4', true);
    expect(dark.colorNeutralBackground2).not.toBe(light.colorNeutralBackground2);
    expect(light.colorBrandBackground).toBe('#0078d4');
    expect(dark.fontFamilyBase).toContain('Segoe UI Variable Text');
    expect(dark.colorBrandForeground1).not.toBe(light.colorBrandForeground1);
  });
});

describe('Portal-Container', () => {
  // Fluent überträgt die className des FluentProvider (Höhe 100 %, Hintergrund) auf Portal-
  // Container. Eine globale Regel mit höherer Spezifität muss sie wieder neutralisieren, sonst
  // liegt der Container deckend über der Seite und die Seite erscheint im Browser leer.
  it('globale Regel macht Portal-Container durchsichtig und ohne Höhe', () => {
    const rule = (GLOBAL_STYLES as Record<string, Record<string, unknown>>)['body > [data-portal-node].fui-FluentProvider'];
    expect(rule).toEqual({ height: 'auto', minHeight: 0, backgroundColor: 'transparent' });
  });
});


describe('Sprungziel-Überschriften', () => {
  it('haben beim programmatischen Fokus keinen Rahmen', () => {
    const rule = (GLOBAL_STYLES as Record<string, Record<string, unknown>>)[
      ':where(h1, h2, h3)[tabindex="-1"]:focus, :where(h1, h2, h3)[tabindex="-1"]:focus-visible'
    ];
    expect(rule).toEqual({ outline: 'none' });
  });
});
