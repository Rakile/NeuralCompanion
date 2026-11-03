import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { clearPersistentMediaCache, mediaCacheUsage } from '../relay/persistentMediaCache';
import { useThemedStyles } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import { idleCacheStatus, refreshIdleCacheStatus, clearPhoneIdleCache } from '../native/idleCacheRuntime';

export function MediaCacheSettings() {
  const styles = useThemedStyles(createStyles);
  const [usage, setUsage] = React.useState<{ bytes: number; files: number; limit: number } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [idle, setIdle] = React.useState(idleCacheStatus);
  const [idleBusy, setIdleBusy] = React.useState(false);
  React.useEffect(() => {
    let active=true,busy=false;
    const refresh=async()=>{if(busy)return;busy=true;try{await refreshIdleCacheStatus();if(active)setIdle(idleCacheStatus());}finally{busy=false;}};
    void refresh();const timer=setInterval(()=>{void refresh();},2000);
    return()=>{active=false;clearInterval(timer);};
  }, []);
  const clearIdle = async () => {
    if (idleBusy) return; setIdleBusy(true); setError('');
    try { await clearPhoneIdleCache(); setIdle(idleCacheStatus()); }
    catch { setError('Could not clear idle animations. A phone app update may be required.'); }
    finally { setIdleBusy(false); }
  };
  React.useEffect(() => { let alive = true; void mediaCacheUsage().then(value => { if (alive) setUsage(value); }).catch(() => { if (alive) setError('Storage information unavailable.'); }); return () => { alive = false; }; }, []);
  const clear = async () => {
    if (busy) return; setBusy(true); setError('');
    try { await clearPersistentMediaCache(); setUsage(await mediaCacheUsage()); }
    catch { setError('Could not clear the cache. Try again.'); }
    finally { setBusy(false); }
  };
  return <View style={styles.body}>
    <Text style={styles.title}>Media storage</Text>
    <Text accessibilityLiveRegion="polite" style={styles.copy}>{usage ? `${(usage.bytes / 1048576).toFixed(1)} MB / ${Math.round(usage.limit / 1048576)} MB · ${usage.files} cached images` : 'Checking storage…'}</Text>
    <Text style={styles.copy}>Avatars and versioned Visual Replies are kept on this phone for Internet reconnects. Old images are removed automatically. Live video and speech stay temporary.</Text>
    <Pressable accessibilityRole="button" accessibilityLabel="Clear cached images" disabled={busy} onPress={() => void clear()} style={styles.button}>
      <Text style={styles.buttonText}>{busy ? 'Clearing…' : 'Clear cached images'}</Text>
    </Pressable>
    <Text style={styles.title}>Idle animation storage</Text>
    <Text accessibilityLiveRegion="polite" style={styles.copy}>{(idle.bytes / 1048576).toFixed(1)} MB / 128 MB · {idle.files} cached idle files · {idle.reason.replace(/_/g, ' ')}</Text>
    {'cacheStats' in idle && <Text style={styles.copy}>This connection: {idle.cacheStats.hits} cache hits · {idle.cacheStats.misses} misses · {(idle.cacheStats.savedBytes / 1048576).toFixed(1)} MB downloads avoided</Text>}
    <Text style={styles.copy}>Optional silent H.264 idle media is reused across moods and reconnects. Enable or disable caching in NC Desktop, then reconnect. Clearing retires files safely; active readers finish before deletion. Speech video is still streamed.</Text>
    <Pressable accessibilityRole="button" accessibilityLabel="Clear cached idle animations" disabled={idleBusy} onPress={() => void clearIdle()} style={styles.button}>
      <Text style={styles.buttonText}>{idleBusy ? 'Clearing…' : 'Clear cached idle animations'}</Text>
    </Pressable>
    {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
  </View>;
}
const createStyles = (colors: ThemeColors) => StyleSheet.create({
  body: { padding: 16, borderRadius: 18, backgroundColor: colors.panel, gap: 10 },
  title: { color: colors.text, fontSize: 17, fontWeight: '600' },
  copy: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  button: { minHeight: 48, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.panelAlt, borderRadius: 12 },
  buttonText: { color: colors.accent, fontSize: 14, fontWeight: '600' },
  error: { color: colors.danger, fontSize: 13 },
});
