import React from 'react';
import {StyleSheet,Text,View} from 'react-native';
import {useThemedStyles} from '../styles/ThemeContext';
import type {ThemeColors} from '../styles/theme';
import type {OrderedIdleInventoryStatus} from '../dev/orderedIdleInventory';

type Props={status:Pick<OrderedIdleInventoryStatus,'reason'|'files'|'totalFiles'>|null;
  bottomInset?:number};

/** One low-frequency status line. Never animates, captures taps, or changes
 * the measured avatar bounds; mount inside the relevant presentation shell. */
export function IdleLoopDownloadStatus({status,bottomInset=0}:Props){
  const styles=useThemedStyles(createStyles);
  if(!status||['disabled','paused','not_connected','cleared'].includes(status.reason))return null;
  const count=status.totalFiles>0?` · ${status.files}/${status.totalFiles} ready`:'';
  let label:string;
  switch(status.reason){
    case 'downloading':label='Idle loops downloading…'+count;break;
    case 'ready':label='Idle loops ready'+count;break;
    case 'storage_limited':label='Idle loop download: storage limit'+count;break;
    case 'incomplete_inventory':label='Some idle loops are unavailable'+count;break;
    case 'gpu_encoder_unavailable':label='Desktop NVIDIA NVENC encoding unavailable · check GPU driver and setup guide';break;
    case 'failed':case 'manifest_failed':label='Idle loop download failed · streamed playback remains available';break;
    case 'reconnecting':label='Idle loop download waiting for connection';break;
    default:label='Preparing idle loop download…';
  }
  return <View pointerEvents="none" style={[styles.overlay,{bottom:Math.max(0,bottomInset)+6}]}>
    <Text accessibilityLiveRegion="polite" numberOfLines={2} style={styles.text}>{label}</Text>
  </View>;
}
const createStyles=(colors:ThemeColors)=>StyleSheet.create({
  overlay:{position:'absolute',left:12,right:12,zIndex:100,alignItems:'center'},
  text:{fontSize:11,lineHeight:15,color:colors.textSecondary,backgroundColor:colors.panel,
    paddingHorizontal:9,paddingVertical:3,borderRadius:8,textAlign:'center'},
});
