/** Stammdaten des Editors: Palette (Buchstaben-Kürzel wie `gui/panels/palette.py`) und Objektnamen. */
import {
  ArrowRight20Regular,
  BarcodeScanner20Regular,
  Image20Regular,
  LineHorizontal120Regular,
  QrCode20Regular,
  RectangleLandscape20Regular,
  Star20Regular,
  TextT20Regular,
  Warning20Regular,
  Grid20Regular,
  type FluentIcon,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { EditorPreset, ObjectKind } from '../../api/types';
import { translateOr } from '../../i18n';

export const PRESET_MIME = 'application/x-tapesmith-preset';

export interface PaletteItem {
  preset: EditorPreset;
  /** Buchstabe auf der Leinwand; der Name kommt aus `editor:palette.<preset>`. */
  key: string;
  icon: FluentIcon;
}

export const PALETTE: PaletteItem[] = [
  { preset: 'text', key: 'T', icon: TextT20Regular },
  { preset: 'qr', key: 'Q', icon: QrCode20Regular },
  { preset: 'code128', key: 'B', icon: BarcodeScanner20Regular },
  { preset: 'datamatrix', key: 'D', icon: Grid20Regular },
  { preset: 'icon', key: 'I', icon: Star20Regular },
  { preset: 'line', key: 'L', icon: LineHorizontal120Regular },
  { preset: 'arrow', key: 'A', icon: ArrowRight20Regular },
  { preset: 'rect', key: 'R', icon: RectangleLandscape20Regular },
  { preset: 'warnbar', key: 'W', icon: Warning20Regular },
  { preset: 'image', key: 'M', icon: Image20Regular },
];

export function presetForKey(key: string): EditorPreset | null {
  const upper = key.toUpperCase();
  return PALETTE.find((p) => p.key === upper)?.preset ?? null;
}

/** Übersetzter Name einer Objektart (wie `KIND_NAMES` in `document/model.py`), unbekannte Arten roh. */
export function useKindName(): (kind: ObjectKind | string) => string {
  // useTranslation sorgt für das Neu-Rendern bei einem Sprachwechsel.
  useTranslation('editor');
  return kindName;
}

export function kindName(kind: ObjectKind | string): string {
  return translateOr(`editor:kinds.${kind}`, kind);
}

/** „Name (id)“ bzw. „Art (id)“; `kindName` ist der übersetzte Name der Objektart. */
export function objectTitle(o: { kind: string; id: string; name?: string }, kindName: (kind: string) => string): string {
  return o.name ? `${o.name} (${o.id})` : `${kindName(o.kind)} (${o.id})`;
}
