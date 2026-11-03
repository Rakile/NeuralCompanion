import * as FileSystem from 'expo-file-system/legacy';

export type IdleFile = {uri: string; release: () => void};
let sequence = 0;

// Idle outlives its speech/trial URL. Own the complete bounded clip until its
// native player releases it; speech segments keep their existing streaming path.
export async function downloadIdleFile(url: string, bytes: number, signal: AbortSignal, ownsLocalFile?: (url: string) => boolean): Promise<IdleFile> {
  if (!FileSystem.cacheDirectory || signal.aborted || !Number.isSafeInteger(bytes) || bytes <= 0 || bytes > 16*1024*1024) {
    throw Error('Idle file unavailable');
  }
  const uri = `${FileSystem.cacheDirectory}nc_musetalk_idle_${Date.now()}_${++sequence}.mp4`;
  let cancelled = false;
  const remove = () => FileSystem.deleteAsync(uri,{idempotent:true}).catch(() => undefined);
  if (/^file:/i.test(url)) {
    // Relay cache entries may be evicted before idle playback ends. Copy only
    // a completed download owned by this live connection, never an arbitrary URI.
    if (!ownsLocalFile?.(url)) throw Error('Idle file unavailable');
    try {
      await FileSystem.copyAsync({from:url,to:uri});
      const info = await FileSystem.getInfoAsync(uri);
      if (signal.aborted || !ownsLocalFile(url) || !info.exists || info.size !== bytes) throw Error('Idle file incomplete');
      let released = false;
      return {uri,release:() => {if (!released) {released=true;void remove();}}};
    } catch {
      await remove(); throw Error('Idle file unavailable');
    }
  }
  const task = FileSystem.createDownloadResumable(url,uri,{},progress => {
    if (progress.totalBytesWritten > bytes) cancel();
  });
  const cancel = () => {
    if (cancelled) return;
    cancelled = true;
    void task.cancelAsync().catch(() => undefined);
  };
  signal.addEventListener('abort',cancel,{once:true});
  const timeout = setTimeout(cancel,15000);
  try {
    const result = await task.downloadAsync();
    const info = await FileSystem.getInfoAsync(uri);
    if (cancelled || signal.aborted || result?.status !== 200 || result.uri !== uri || !info.exists || info.size !== bytes) {
      throw Error('Idle file incomplete');
    }
    let released = false;
    return {uri,release:() => {if (!released) {released=true;void remove();}}};
  } catch {
    await remove();
    throw Error('Idle file unavailable');
  } finally {
    clearTimeout(timeout);signal.removeEventListener('abort',cancel);
  }
}
