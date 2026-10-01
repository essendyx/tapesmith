import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { BluetoothSettingsButton } from '../BluetoothSettingsButton';
import { mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';

afterEach(() => restoreAllMocks());

describe('BluetoothSettingsButton', () => {
  it('öffnet die Bluetooth-Einstellungen über die API', async () => {
    let opened = 0;
    mockApi({ 'POST /api/v1/system/open-bluetooth-settings': () => { opened += 1; return { opened: 'ms-settings:bluetooth' }; } });
    const { user } = renderWithProviders(<BluetoothSettingsButton />);
    await user.click(await screen.findByRole('button', { name: /Bluetooth-Einstellungen/ }));
    await waitFor(() => expect(opened).toBe(1));
  });
});
