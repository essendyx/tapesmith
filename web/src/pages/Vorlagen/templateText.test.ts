import { describe, expect, it } from 'vitest';
import { categoryKind, placeholderValue, shortDescription, templateTitle } from './templateText';
import type { FieldJson } from '../../api/types';

const field = (o: Partial<FieldJson> = {}): FieldJson => ({
  id: 'name', label: 'Name', type: 'input', default: '', required: true, secret: false, choices: [], max_len: null, multiline: false, ...o,
});

describe('templateText', () => {
  it('Titel: eigener Titel, sonst lesbare ID', () => {
    expect(templateTitle({ name: 'eigentum', title: 'Eigentum' })).toBe('Eigentum');
    expect(templateTitle({ name: 'ordnerruecken-breit' })).toBe('Ordnerruecken breit');
    expect(templateTitle({ name: 'vm_lxc', title: 'vm_lxc' })).toBe('Vm lxc');
  });

  it('Kurzbeschreibung: erster Satz ohne Schlusszeichen', () => {
    expect(shortDescription('Absenderetikett (3 Zeilen): Name, Straße, Ort. Mehr.')).toBe('Absenderetikett (3 Zeilen)');
    expect(shortDescription('Garantie-Etikett. Rest')).toBe('Garantie-Etikett');
    expect(shortDescription('Ohne Satzende')).toBe('Ohne Satzende');
  });

  it('Beispielwert: Vorlagenbeispiel, Standard, erste Auswahl, Bezeichnung', () => {
    expect(placeholderValue(field(), { name: 'Max' })).toBe('Max');
    expect(placeholderValue(field({ default: 'Std' }), {})).toBe('Std');
    expect(placeholderValue(field({ choices: ['A', 'B'] }), {})).toBe('A');
    expect(placeholderValue(field(), {})).toBe('Name');
  });

  it('Kategorie-Symbol auf Deutsch und Englisch', () => {
    expect(categoryKind('Haushalt')).toBe('home');
    expect(categoryKind('Household')).toBe('home');
    expect(categoryKind('Disks')).toBe('disks');
    expect(categoryKind('Eigene')).toBe('other');
  });
});
