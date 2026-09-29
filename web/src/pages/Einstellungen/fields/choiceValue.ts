import type { SettingField } from '../../../api/types';

/** Auswahllisten liefern immer Text: den echten Wert der Auswahl zurückgeben (Zahl oder null, also 5 statt "5"). */
export function choiceValue(field: SettingField, text: string): unknown {
  const match = (field.choices ?? []).find((c) => (c.value === null ? '' : String(c.value)) === text);
  return match ? match.value : text;
}
