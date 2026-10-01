/** Öffnet die Bluetooth-Geräte in den Windows-Einstellungen (nur am PC selbst), damit der
 * Drucker dort mit einem Klick verbunden werden kann. */
import { useState } from 'react';
import { Button } from '@fluentui/react-components';
import { Bluetooth20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { apiPost } from '../api/client';

export function openBluetoothSettings(): Promise<{ opened: string }> {
  return apiPost<{ opened: string }>('/api/v1/system/open-bluetooth-settings');
}

export function BluetoothSettingsButton(props: { onError?: (err: unknown) => void }): JSX.Element {
  const { t } = useTranslation('shell');
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try {
      await openBluetoothSettings();
    } catch (err) {
      props.onError?.(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button appearance="secondary" icon={<Bluetooth20Regular />} disabled={busy} onClick={() => void open()}
      title={t('bluetooth.hint')}>
      {t('bluetooth.open')}
    </Button>
  );
}
