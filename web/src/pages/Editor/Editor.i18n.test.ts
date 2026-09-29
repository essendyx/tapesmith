import { createElement, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';
import { fixtures, mockApi, renderWithProviders, SLOW_UI_MS } from '../../test/utils';
import EditorPage from './index';

vi.mock('react-konva', async () => {
  const { createElement: h } = await import('react');
  const Box = (props: { children?: ReactNode }) => h('div', null, props.children);
  const Leaf = () => null;
  return { Stage: Box, Layer: Box, Group: Box, Rect: Leaf, Line: Leaf, Image: Leaf, Text: Leaf };
});

const tsx = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const ts = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = { ...tsx, ...ts };

describe('Editor: Übersetzung', () => {
  it('keine deutschen Literale in pages/Editor (außer Tests)', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(15);
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben (die Bandfarbe ist ausgenommen)', () => {
    expect(findHardcodedColors(sources, [/Bandfarbe/])).toEqual([]);
  });

  it('Englisch: Überschrift, Drucken, Eigenschaften und Ebenen', async () => {
    mockApi({
      'GET /api/v1/drafts': () => ({ drafts: [], own: [], orphaned: [] }),
      'PUT /api/v1/drafts/:id': ({ params }) => ({ id: params.id }),
      'GET /api/v1/labels/fonts': () => ({ fonts: [] }),
      'GET /api/v1/targets': () => ({ targets: [] }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    renderWithProviders(createElement(EditorPage), { route: '/editor', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Editor' })).toBeInTheDocument();
    await screen.findByRole('application', {}, { timeout: SLOW_UI_MS });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument());
    expect(screen.getByRole('tab', { name: 'Properties' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Layers' })).toBeInTheDocument();
    expect(screen.getByRole('tablist', { name: 'Open labels' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Untitled' })).toBeInTheDocument();
    expect(screen.getByText('Empty label')).toBeInTheDocument();
    expect(screen.getByRole('toolbar', { name: 'Editor tools' })).toBeInTheDocument();
  });
});
