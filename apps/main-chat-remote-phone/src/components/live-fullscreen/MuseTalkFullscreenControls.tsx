import React from 'react';
import {BackHandler, StyleSheet, View} from 'react-native';
import type {LiveFullscreenSettings} from '../../utils/liveFullscreenSettings';
import type {MuseTalkZoomGestures} from '../../hooks/useMuseTalkFullscreenZoom';
import {LiveFullscreenActionTray} from './LiveFullscreenActionTray';
import {LiveFullscreenGestureLayer} from './LiveFullscreenGestureLayer';
import {IdleLoopDownloadStatus} from '../IdleLoopDownloadStatus';

type Props = Omit<React.ComponentProps<typeof LiveFullscreenActionTray>, 'visible' | 'includeExit' | 'onClose' | 'dismissOnBackdrop'> & {
  settings: Pick<LiveFullscreenSettings, 'longPressSeconds' | 'vibrationEnabled' | 'plongEnabled'>;
  zoomGestures: MuseTalkZoomGestures;
  idleStatus?:React.ComponentProps<typeof IdleLoopDownloadStatus>['status'];
};
const noop = () => {};

// Mounted only as fullscreen chrome; the video lives in its unchanged sibling.
export function MuseTalkFullscreenControls({settings, onExit, zoomGestures, idleStatus, ...actions}: Props) {
  const [trayMode, setTrayMode] = React.useState<'double' | null>(null);
  const closeTray = React.useCallback(() => setTrayMode(null), []);
  React.useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (trayMode !== null) closeTray();
      else onExit();
      return true;
    });
    return () => subscription.remove();
  }, [trayMode, closeTray, onExit]);

  return <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
    <LiveFullscreenGestureLayer
      longPressSeconds={settings.longPressSeconds} longPressEnabled={false} vibrationEnabled={settings.vibrationEnabled}
      plongEnabled={settings.plongEnabled} transformEnabled={trayMode === null}
      accessibilityEnabled={trayMode === null} accessibilityLabel="Fullscreen avatar view"
      onSingleTap={noop} onDoubleTap={() => setTrayMode('double')} onLongPress={noop}
      {...zoomGestures} />
    <LiveFullscreenActionTray {...actions} visible={trayMode !== null} includeExit dismissOnBackdrop
      onClose={closeTray} onExit={onExit} />
    <IdleLoopDownloadStatus status={idleStatus??null} bottomInset={20} />
  </View>;
}
