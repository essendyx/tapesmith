import { describe, expect, it } from 'vitest';
import { fold, fuzzyScore, searchCommands } from './fuzzy';
import type { CommandDef } from './registry';

const cmd = (title: string, keywords: string[] = [], group = 'Test'): CommandDef => ({
  id: title,
  title,
  group,
  keywords,
  run: () => {},
});

describe('fuzzyScore', () => {
  it('Stichwort „wieder“ trifft „Letztes erneut drucken“', () => {
    expect(fuzzyScore('wieder', cmd('Letztes erneut drucken', ['wieder', 'nochmal', 'reprint']))).toBe(100);
  });

  it('„einst“ trifft „Einstellungen öffnen“', () => {
    expect(fuzzyScore('einst', cmd('Einstellungen öffnen'))).toBe(80);
  });

  it('Umlaute: „datentrager“ und „datentraeger“ treffen „Datenträger-Assistent“', () => {
    expect(fuzzyScore('datentrager', cmd('Datenträger-Assistent'))).toBeGreaterThan(0);
    expect(fuzzyScore('datentraeger', cmd('Datenträger-Assistent'))).toBeGreaterThan(0);
  });

  it('Initialen und Teilfolge', () => {
    expect(fuzzyScore('led', cmd('Letztes erneut drucken'))).toBe(20);
    expect(fuzzyScore('ltzt', cmd('Letztes erneut drucken'))).toBe(10);
    expect(fuzzyScore('xyz', cmd('Letztes erneut drucken'))).toBe(0);
  });

  it('fold entfernt Akzente und ß', () => {
    expect(fold('Straße Café Ärger')).toBe('strasse cafe arger');
  });

  it('searchCommands sortiert nach Punktzahl und blendet deaktivierte aus', () => {
    const list = [
      cmd('SSH-Disk-Scanner'),
      cmd('Neues SSD-/Datenträger-Etikett', ['ssd', 'hdd']),
      { ...cmd('SSD aus'), enabled: () => false },
    ];
    expect(searchCommands('ssd', list).map((c) => c.title)).toEqual(['Neues SSD-/Datenträger-Etikett', 'SSH-Disk-Scanner']);
  });
});
