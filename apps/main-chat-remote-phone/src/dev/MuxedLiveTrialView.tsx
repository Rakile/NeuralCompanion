import React from 'react';
import {View,StyleSheet} from 'react-native';
import type {ViewProps,NativeSyntheticEvent} from 'react-native';
import {requireNativeView} from 'expo';
import type {AudioPlayer} from 'expo-audio';

/** The exact queue-owned player supplies both tracks. Retain the existing
 * picture underneath until that player's actual first rendered frame, never
 * hide it on download, READY, or an audio playing flag. No receipt authority.
 */
export function MuxedLiveTrialView(props:{player:AudioPlayer|null;fallback:React.ReactNode;onReady?:()=>void;
  hideFallbackWhenReady?:boolean}) {
  const NativeView=React.useMemo(()=>requireNativeView<ViewProps&{player:number;
    onReady(event:NativeSyntheticEvent<{playerId:string}>):void}>('ExpoAudio','NCMuxedTrialView'),[]);
  const [ready,setReady]=React.useState('');
  const player=props.player,id=player?String(player.id):'';
  // Expo's view prop converter resolves SharedObjects by registry handle. The
  // AudioPlayer object itself is a map here; player.id is a different identity.
  const handle=(player as (AudioPlayer&{__expo_shared_object_id__?:number})|null)?.__expo_shared_object_id__;
  const nativeAvailable=Boolean(player&&Number.isSafeInteger(handle)&&handle!>0);
  const hideFallback=Boolean(props.hideFallbackWhenReady&&nativeAvailable&&ready===id);
  const current=React.useRef(id);current.current=id;
  return <View style={[styles.host,props.hideFallbackWhenReady&&styles.opaque]}>
    {props.hideFallbackWhenReady?<View pointerEvents="none" accessibilityElementsHidden={hideFallback}
      importantForAccessibility={hideFallback?'no-hide-descendants':'auto'}
      style={[StyleSheet.absoluteFillObject,{opacity:hideFallback?0:1}]}>{props.fallback}</View>:props.fallback}
    {player&&Number.isSafeInteger(handle)&&handle!>0?<NativeView key={id} player={handle!}
      onReady={event=>{if(event.nativeEvent.playerId===id&&current.current===id){setReady(id);props.onReady?.();}}}
      style={[StyleSheet.absoluteFillObject,{opacity:ready===id?1:0}]} />:null}
  </View>;
}
const styles=StyleSheet.create({host:{flex:1},opaque:{backgroundColor:'#000'}});
