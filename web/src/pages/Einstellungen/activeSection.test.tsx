/** Prüft, dass die Sprungliste den Abschnitt hervorhebt, der laut IntersectionObserver gerade sichtbar ist. */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, waitFor } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import { baseSettingsRoutes } from './testFixtures';
import EinstellungenPage from './index';

type ObserverCallback = (entries: Partial<IntersectionObserverEntry>[]) => void;

class FakeIntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];
  observed: Element[] = [];
  constructor(private cb: ObserverCallback) {
    FakeIntersectionObserver.instances.push(this);
  }
  observe(el: Element): void {
    this.observed.push(el);
  }
  unobserve(): void {}
  disconnect(): void {}
  trigger(entries: Partial<IntersectionObserverEntry>[]): void {
    this.cb(entries);
  }
}

const realIntersectionObserver = (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;

beforeEach(() => {
  FakeIntersectionObserver.instances = [];
  (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = FakeIntersectionObserver;
});

afterEach(() => {
  (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = realIntersectionObserver;
});

describe('Sprungliste: aktiver Abschnitt beim Scrollen', () => {
  it('markiert den Abschnitt, den der IntersectionObserver als sichtbar meldet', async () => {
    mockApi(baseSettingsRoutes());
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    await waitFor(() => expect(document.getElementById('kalibrierung')).not.toBeNull());
    await waitFor(() => expect(FakeIntersectionObserver.instances.length).toBeGreaterThan(0));
    const observer = FakeIntersectionObserver.instances[FakeIntersectionObserver.instances.length - 1] as FakeIntersectionObserver;
    const target = document.getElementById('kalibrierung') as HTMLElement;
    expect(observer.observed).toContain(target);

    const link = document.querySelector('a[href="#kalibrierung"]') as HTMLElement;
    expect(link).not.toBeNull();
    expect(link).not.toHaveAttribute('aria-current');

    // Der Observer-Callback setzt State in EinstellungenPage, daher in act() auslösen.
    act(() => {
      observer.trigger([{ target, isIntersecting: true, intersectionRatio: 1 }]);
    });

    await waitFor(() => expect(link).toHaveAttribute('aria-current', 'true'));
  });
});
