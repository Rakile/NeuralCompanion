import { useCallback, useEffect, useState } from 'react';
import * as SecureStore from 'expo-secure-store';

import {
  emptyConnectionSettings,
  normalizeConnectionSettings,
  type ConnectionMode,
  type InternetConnectionProfile,
  type LanConnectionProfile,
  type StoredConnectionSettingsV2,
} from '../utils/connectionProfiles';

export const CONNECTION_SETTINGS_V2_KEY = 'nc-main-chat-remote.connection.v2';
const LEGACY_CONNECTION_SETTINGS_KEY = 'nc-main-chat-remote.connection';

export function useConnectionProfiles() {
  const [settings, setSettings] = useState<StoredConnectionSettingsV2>(() => emptyConnectionSettings());
  const [loaded, setLoaded] = useState(false);
  const [credentialGeneration, setCredentialGeneration] = useState(0);

  useEffect(() => {
    let alive = true;
    Promise.all([
      SecureStore.getItemAsync(CONNECTION_SETTINGS_V2_KEY),
      SecureStore.getItemAsync(LEGACY_CONNECTION_SETTINGS_KEY),
    ])
      .then(([current, legacy]) => {
        if (!alive) return;
        const source = current || legacy;
        let parsed: unknown = {};
        if (source) {
          try {
            parsed = JSON.parse(source);
          } catch {
            parsed = {};
          }
        }
        setSettings(normalizeConnectionSettings(parsed));
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!loaded) return;
    SecureStore.setItemAsync(CONNECTION_SETTINGS_V2_KEY, JSON.stringify(settings))
      .then(() => SecureStore.deleteItemAsync(LEGACY_CONNECTION_SETTINGS_KEY))
      .catch(() => undefined);
  }, [loaded, settings]);

  const update = useCallback((next: StoredConnectionSettingsV2) => {
    setSettings(normalizeConnectionSettings(next));
  }, []);

  const setMode = useCallback((mode: ConnectionMode) => {
    setSettings((current) => normalizeConnectionSettings({ ...current, mode }));
  }, []);

  const setLan = useCallback((lan: LanConnectionProfile) => {
    setSettings((current) => normalizeConnectionSettings({ ...current, lan }));
  }, []);

  const setInternet = useCallback((internet: InternetConnectionProfile) => {
    setSettings((current) => normalizeConnectionSettings({ ...current, internet }));
    setCredentialGeneration((value) => value + 1);
  }, []);

  const forgetInternet = useCallback(() => {
    setSettings((current) => normalizeConnectionSettings({
      ...current,
      internet: { hostnameUrl: '', ipUrl: '', deviceId: '', gatewayId: '', deviceToken: '' },
    }));
    setCredentialGeneration((value) => value + 1);
  }, []);

  return {
    settings,
    loaded,
    credentialGeneration,
    update,
    setMode,
    setLan,
    setInternet,
    forgetInternet,
  };
}
