/** Feste Einträge der Tastenkürzel-Übersicht. Beschreibungen über `commands:shortcuts.*`. */

export type CatalogGroup = 'global' | 'editor' | 'editorTabs';

export interface CatalogEntry {
  id: string;
  group: CatalogGroup;
  /** Kürzel in der Form von `useShortcut` ("Ctrl+Shift+V"); mehrere sind Alternativen. */
  combos: string[];
  /** Statt der Kürzel ein eigener Anzeigetext (`commands:shortcuts.keys.*`), z. B. „Pfeiltasten“. */
  keysLabel?: 'digits' | 'arrows' | 'shiftArrows';
  /** Schlüssel unter `commands:shortcuts.items`. */
  description: string;
}

export const CATALOG_GROUPS: readonly CatalogGroup[] = ['global', 'editor', 'editorTabs'];

export const SHORTCUT_CATALOG: readonly CatalogEntry[] = [
  { id: 'palette', group: 'global', combos: ['Ctrl+K'], description: 'palette' },
  { id: 'print', group: 'global', combos: ['Ctrl+P'], description: 'print' },
  { id: 'navigate', group: 'global', combos: ['Ctrl+1'], keysLabel: 'digits', description: 'navigate' },
  { id: 'settings', group: 'global', combos: ['Ctrl+,'], description: 'settings' },
  { id: 'clipboardImport', group: 'global', combos: ['Ctrl+Shift+V'], description: 'clipboardImport' },
  { id: 'cancelPrint', group: 'global', combos: ['Escape'], description: 'cancelPrint' },
  { id: 'cutContinue', group: 'global', combos: ['Space'], description: 'cutContinue' },
  { id: 'help', group: 'global', combos: ['?', 'F1'], description: 'help' },
  { id: 'undo', group: 'editor', combos: ['Ctrl+Z'], description: 'undo' },
  { id: 'redo', group: 'editor', combos: ['Ctrl+Y'], description: 'redo' },
  { id: 'redoAlt', group: 'editor', combos: ['Ctrl+Shift+Z'], description: 'redoAlt' },
  { id: 'delete', group: 'editor', combos: ['Delete'], description: 'delete' },
  { id: 'duplicate', group: 'editor', combos: ['Ctrl+D'], description: 'duplicate' },
  { id: 'rotate', group: 'editor', combos: ['Ctrl+R'], description: 'rotate' },
  { id: 'rotateBack', group: 'editor', combos: ['Ctrl+Shift+R'], description: 'rotateBack' },
  { id: 'flip', group: 'editor', combos: ['Ctrl+M'], description: 'flip' },
  { id: 'selectAll', group: 'editor', combos: ['Ctrl+A'], description: 'selectAll' },
  { id: 'save', group: 'editor', combos: ['Ctrl+S'], description: 'save' },
  { id: 'deselect', group: 'editor', combos: ['Escape'], description: 'deselect' },
  { id: 'move', group: 'editor', combos: ['ArrowRight'], keysLabel: 'arrows', description: 'move' },
  { id: 'moveFine', group: 'editor', combos: ['Shift+ArrowRight'], keysLabel: 'shiftArrows', description: 'moveFine' },
  { id: 'tabNew', group: 'editorTabs', combos: ['Ctrl+Alt+T'], description: 'tabNew' },
  { id: 'tabClose', group: 'editorTabs', combos: ['Ctrl+Alt+W'], description: 'tabClose' },
  { id: 'tabNext', group: 'editorTabs', combos: ['Ctrl+PageDown'], description: 'tabNext' },
  { id: 'tabPrev', group: 'editorTabs', combos: ['Ctrl+PageUp'], description: 'tabPrev' },
];
