/** Endpunkte der Einstellungsseite. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPatch, apiDelete, apiPost } from '../../api/client';
import { qk } from '../../api/core';
import type {
  BackupJson,
  CalibrationJson,
  DaemonJson,
  IntegrationJson,
  RollsJson,
  SettingsJson,
  SetupJson,
  TemplateSummary,
  TransportChoice,
} from '../../api/types';

export function useSettings(): UseQueryResult<SettingsJson> {
  return useQuery({ queryKey: qk.settings, queryFn: ({ signal }) => apiGet<SettingsJson>('/api/v1/settings', signal) });
}

export function patchSettings(changes: Record<string, unknown>): Promise<SettingsJson> {
  return apiPatch<SettingsJson>('/api/v1/settings', { changes });
}

export function useSettingsPorts(): UseQueryResult<{ transports: TransportChoice[] }> {
  return useQuery({
    queryKey: ['settings-ports'],
    queryFn: ({ signal }) => apiGet<{ transports: TransportChoice[] }>('/api/v1/settings/ports', signal),
  });
}

export function postSetup(payload: { port?: string | null; test_label: boolean }): Promise<SetupJson> {
  return apiPost<SetupJson>('/api/v1/settings/setup', payload);
}

export function useRolls(): UseQueryResult<RollsJson> {
  return useQuery({ queryKey: qk.rolls, queryFn: ({ signal }) => apiGet<RollsJson>('/api/v1/rolls', signal) });
}

export function postNewRoll(payload: { tape_id?: string; length_mm?: number }): Promise<RollsJson> {
  return apiPost<RollsJson>('/api/v1/rolls/new', payload);
}

export function postRollEmpty(payload: { at_mm?: number | null }): Promise<RollsJson> {
  return apiPost<RollsJson>('/api/v1/rolls/empty', payload);
}

export function useCalibration(): UseQueryResult<CalibrationJson> {
  return useQuery({ queryKey: ['calibration'], queryFn: ({ signal }) => apiGet<CalibrationJson>('/api/v1/calibration', signal) });
}

export function postCalibrationLength(payload: {
  measured_mm: number;
  leader_mm?: number | null;
  trailer_mm?: number | null;
}): Promise<CalibrationJson> {
  return apiPost<CalibrationJson>('/api/v1/calibration/length', payload);
}

/** Längenfaktor zurücksetzen: danach gilt der Wert aus dem Geräteprofil (meist 1,0). */
export function resetCalibrationLength(): Promise<CalibrationJson> {
  return apiDelete<CalibrationJson>('/api/v1/calibration/length');
}

export function useDaemon(): UseQueryResult<DaemonJson> {
  return useQuery({ queryKey: ['daemon'], queryFn: ({ signal }) => apiGet<DaemonJson>('/api/v1/daemon', signal) });
}

export function useIntegration(): UseQueryResult<IntegrationJson> {
  return useQuery({ queryKey: ['integration'], queryFn: ({ signal }) => apiGet<IntegrationJson>('/api/v1/integration', signal) });
}

export interface IntegrationPayload {
  context: boolean;
  uri: boolean;
  autostart: boolean;
  dry_run: boolean;
}

export function postIntegrationInstall(payload: IntegrationPayload): Promise<IntegrationJson> {
  return apiPost<IntegrationJson>('/api/v1/integration/install', payload);
}

export function postIntegrationUninstall(payload: IntegrationPayload): Promise<IntegrationJson> {
  return apiPost<IntegrationJson>('/api/v1/integration/uninstall', payload);
}

export function useBackups(): UseQueryResult<{ dir: string; backups: BackupJson[] }> {
  return useQuery({ queryKey: ['backups'], queryFn: ({ signal }) => apiGet<{ dir: string; backups: BackupJson[] }>('/api/v1/backups', signal) });
}

export function postBackupNow(): Promise<BackupJson> {
  return apiPost<BackupJson>('/api/v1/backups', {});
}

export function postBackupRestore(payload: { name: string; dry_run: boolean }): Promise<{ lines: string[] }> {
  return apiPost<{ lines: string[] }>('/api/v1/backups/restore', payload);
}

export function postConfigExport(payload: {
  dir: string;
  include_templates: boolean;
  strip_secrets: boolean;
}): Promise<{ files: string[] }> {
  return apiPost<{ files: string[] }>('/api/v1/config/export', payload);
}

export function postConfigImport(payload: {
  dir: string;
  dry_run: boolean;
  include_templates: boolean;
}): Promise<{ changes: string[]; warnings: string[]; backup_dir: string | null }> {
  return apiPost<{ changes: string[]; warnings: string[]; backup_dir: string | null }>('/api/v1/config/import', payload);
}

export function useTemplatesQuiet(): UseQueryResult<{ templates: TemplateSummary[] }> {
  return useQuery({
    queryKey: qk.templates,
    queryFn: ({ signal }) => apiGet<{ templates: TemplateSummary[] }>('/api/v1/templates', signal),
    retry: false,
  });
}
