/** Token-Eingabe im Hinweisschirm ohne Token (außerhalb des App-Fensters). */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import { NoTokenScreen } from '../NoTokenScreen';
import { getToken, REMEMBER_KEY, setTokenForTests, TOKEN_KEY } from '../../api/client';

function renderScreen(props?: { expired?: boolean; onLogin?: () => void }) {
  mockApi({}, { quiet: true });
  const { user } = renderWithProviders(<NoTokenScreen {...props} />, { token: null });
  return { user };
}

afterEach(() => {
  delete window.pywebview;
  setTokenForTests(null);
  sessionStorage.clear();
  localStorage.clear();
});

describe('NoTokenScreen: Token-Eingabe außerhalb des App-Fensters', () => {
  it('zeigt ein Passwortfeld, Knopf ist deaktiviert bis zur Eingabe', async () => {
    const { user } = renderScreen();
    const field = screen.getByLabelText('Zugangstoken');
    expect(field).toHaveAttribute('type', 'password');
    const button = screen.getByRole('button', { name: 'Anmelden' });
    expect(button).toBeDisabled();
    await user.type(field, 'p12_abc123');
    expect(button).toBeEnabled();
  });

  it('Eingabe plus „Anmelden“ ruft onLogin und speichert das Token in sessionStorage', async () => {
    const onLogin = vi.fn();
    const { user } = renderScreen({ onLogin });
    await user.type(screen.getByLabelText('Zugangstoken'), 'p12_abc123');
    await user.click(screen.getByRole('button', { name: 'Anmelden' }));
    expect(onLogin).toHaveBeenCalledTimes(1);
    expect(getToken()).toBe('p12_abc123');
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe('p12_abc123');
    expect(localStorage.getItem(REMEMBER_KEY)).toBeNull();
  });

  it('mit „merken“ speichert das Token zusätzlich in localStorage', async () => {
    const onLogin = vi.fn();
    const { user } = renderScreen({ onLogin });
    await user.type(screen.getByLabelText('Zugangstoken'), 'p12_abc123');
    await user.click(screen.getByRole('checkbox', { name: 'Auf diesem Gerät merken' }));
    await user.click(screen.getByRole('button', { name: 'Anmelden' }));
    expect(localStorage.getItem(REMEMBER_KEY)).toBe('p12_abc123');
  });

  it('Enter im Feld löst „Anmelden“ aus', async () => {
    const onLogin = vi.fn();
    const { user } = renderScreen({ onLogin });
    const field = screen.getByLabelText('Zugangstoken');
    await user.type(field, 'p12_abc123{Enter}');
    expect(onLogin).toHaveBeenCalledTimes(1);
  });

  it('leerer Wert: Knopf bleibt deaktiviert, Leerzeichen zählen nicht', async () => {
    const { user } = renderScreen();
    const field = screen.getByLabelText('Zugangstoken');
    await user.type(field, '   ');
    expect(screen.getByRole('button', { name: 'Anmelden' })).toBeDisabled();
  });

  it('zeigt den Hinweis auf tapesmith token add', () => {
    renderScreen();
    expect(screen.getByText(/Tokens legt die Verwaltung unter Zugriff an/)).toBeInTheDocument();
    expect(screen.getByText(/tapesmith token add/)).toBeInTheDocument();
  });
});

describe('NoTokenScreen: im App-Fenster', () => {
  it('zeigt kein Formular', () => {
    window.pywebview = { api: { retry: vi.fn(() => Promise.resolve()) } };
    renderScreen();
    expect(screen.queryByLabelText('Zugangstoken')).toBeNull();
  });
});

describe('NoTokenScreen: expired', () => {
  it('zeigt den Hinweis „ungültig oder wurde widerrufen“ und „Anderes Token eingeben“ leert die Speicher', async () => {
    setTokenForTests('alt');
    sessionStorage.setItem(TOKEN_KEY, 'alt');
    localStorage.setItem(REMEMBER_KEY, 'alt');
    const { user } = renderScreen({ expired: true });
    expect(screen.getByText(/ungültig oder wurde widerrufen/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Anderes Token eingeben' }));
    expect(getToken()).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REMEMBER_KEY)).toBeNull();
    expect(screen.getByLabelText('Zugangstoken')).toBeInTheDocument();
  });
});

describe('NoTokenScreen: Englisch', () => {
  it('Formular und Hinweise englisch', () => {
    mockApi({}, { quiet: true });
    renderWithProviders(<NoTokenScreen />, { token: null, language: 'en' });
    expect(screen.getByText('Sign-in required')).toBeInTheDocument();
    expect(screen.getByLabelText('Access token')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByText(/tapesmith token add/)).toBeInTheDocument();
  });
});
