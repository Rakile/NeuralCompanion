import React from 'react';
import {Pressable,StyleSheet,Text,View} from 'react-native';

export function PendingVoiceRecording({recording,busy,onSend,onDiscard}:{
  recording:{id:string;canSend:boolean};busy:boolean;onSend():Promise<void>;onDiscard():Promise<void>
}){
  return <View style={styles.card}>
    <Text style={styles.text}>{recording.canSend?'Recording not sent':'Recording send unconfirmed — automatic retry blocked'}</Text>
    <Pressable accessibilityRole="button" accessibilityLabel="Send retained recording" disabled={busy||!recording.canSend}
      onPress={()=>{void onSend();}} style={styles.button}><Text style={styles.text}>Send</Text></Pressable>
    <Pressable accessibilityRole="button" accessibilityLabel="Discard retained recording" disabled={busy}
      onPress={()=>{void onDiscard();}} style={styles.button}><Text style={styles.text}>Discard</Text></Pressable>
  </View>;
}
const styles=StyleSheet.create({card:{padding:10,gap:8,borderWidth:1,borderColor:'#55d6f5',borderRadius:12,
  backgroundColor:'#102532'},text:{color:'#e7f7ff'},button:{padding:10,borderRadius:8,borderWidth:1,borderColor:'#55d6f5'}});
