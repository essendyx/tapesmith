import { afterEach, describe, expect, it } from 'vitest';
import { i18n } from './index';
import { displayTitle } from './systemTitle';

afterEach(() => {
  void i18n.changeLanguage('de');
});

describe('displayTitle', () => {
  it('übersetzt Systemtitel anhand der Art in die Oberflächensprache', async () => {
    await i18n.changeLanguage('en');
    expect(displayTitle('Kalibrierung Lineal', 'calibrate')).toBe('Calibration ruler');
    expect(displayTitle('Kalibrierung Kantentest', 'calibrate')).toBe('Calibration edge test');
    expect(displayTitle('Kalibrierung edge', 'calibrate')).toBe('Calibration edge test');
    expect(displayTitle('Testlabel', 'test')).toBe('Test label');
    expect(displayTitle('Bild aus Zwischenablage', 'image')).toBe('Image from clipboard');
    expect(displayTitle('Nachdruck #7: Kalibrierung Lineal', 'reprint')).toBe('Reprint #7: Calibration ruler');
    expect(displayTitle('Serie (3): K-020 SW2/P01', 'template')).toBe('Series (3): K-020 SW2/P01');
  });

  it('übersetzt englische Systemtitel zurück ins Deutsche', async () => {
    await i18n.changeLanguage('de');
    expect(displayTitle('Calibration ruler', 'calibrate')).toBe('Kalibrierung Lineal');
    expect(displayTitle('Reprint #2: pmx10', 'reprint')).toBe('Nachdruck #2: pmx10');
  });

  it('lässt Nutzertitel unverändert', async () => {
    await i18n.changeLanguage('en');
    expect(displayTitle('Testlabel', 'text')).toBe('Testlabel');
    expect(displayTitle('Kalibrierung Lineal', 'template')).toBe('Kalibrierung Lineal');
    expect(displayTitle('WLAN im Keller', 'qr', {})).toBe('WLAN im Keller');
    expect(displayTitle('Nachdruck #1: Serverschrank', 'reprint')).toBe('Reprint #1: Serverschrank');
  });

  it('WLAN-QR mit Passwort wird nur mit Kennzeichen übersetzt', async () => {
    await i18n.changeLanguage('en');
    expect(displayTitle('WLAN Homelab-IoT (Passwort •••)', 'qr', { qr_kind: 'wifi' })).toBe('Wi-Fi Homelab-IoT (password •••)');
  });

  it('Warteschlange ohne Art: nur vollständige Systemtitel und Präfixe', async () => {
    await i18n.changeLanguage('en');
    expect(displayTitle('Kalibrierung Lineal')).toBe('Calibration ruler');
    expect(displayTitle('Serie (4): K-021')).toBe('Series (4): K-021');
    expect(displayTitle('pmx10 SSD-4')).toBe('pmx10 SSD-4');
  });
});
