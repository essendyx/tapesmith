import { describe, expect, it } from 'vitest';
import { choiceValue } from './choiceValue';
import type { SettingField } from '../../../api/types';

const field: SettingField = {
  key: 'cut_pause_s', label: 'Schneidpause', type: 'choice', value: null, default: null, nullable: true,
  choices: [{ value: null, label: 'bis Weiter' }, { value: 0, label: 'aus' }, { value: 5, label: '5 s' }, { value: 'auto', label: 'auto' }],
};

describe('choiceValue', () => {
  it('liefert Zahlen, null und Texte im echten Typ', () => {
    expect(choiceValue(field, '5')).toBe(5);
    expect(choiceValue(field, '0')).toBe(0);
    expect(choiceValue(field, '')).toBeNull();
    expect(choiceValue(field, 'auto')).toBe('auto');
  });
});
