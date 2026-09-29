/** Kontext für die geteilte Bearbeitungssitzung der generischen Einstellungsfelder. */
import { createContext, useContext } from 'react';
import type { SettingsEditor } from './useSettingsEditor';

export const SettingsEditContext = createContext<SettingsEditor | null>(null);

export function useSettingsEdit(): SettingsEditor {
  const ctx = useContext(SettingsEditContext);
  if (!ctx) throw new Error('useSettingsEdit ohne SettingsEditContext.Provider');
  return ctx;
}
