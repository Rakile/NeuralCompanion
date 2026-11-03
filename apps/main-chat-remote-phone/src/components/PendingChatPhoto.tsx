import React from 'react';
import {Image,Pressable,StyleSheet,Text,View} from 'react-native';
import type {ChatPhotoDraft} from '../hooks/useChatPhotoDraft';

export function PendingChatPhoto({draft,disabled=false}:{draft?:ChatPhotoDraft;disabled?:boolean}) {
  if(!draft)return null;
  return <View>
    {draft.photo?<View style={styles.row}>
      <Image source={{uri:draft.photo.uri}} accessibilityLabel="Attached photo preview" style={styles.preview}/>
      <Text style={styles.text}>Photo attached · add a message or tap Send</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Remove attached photo" disabled={disabled||draft.busy} onPress={draft.clear} style={styles.remove}>
        <Text style={styles.text}>Remove</Text>
      </Pressable>
    </View>:null}
    {draft.error?<Text accessibilityRole="alert" style={styles.error}>{draft.error}</Text>:null}
  </View>;
}
const styles=StyleSheet.create({row:{flexDirection:'row',alignItems:'center',gap:8},preview:{width:44,height:44,borderRadius:6},
  text:{color:'#d9edf7',fontSize:12,flexShrink:1},remove:{minHeight:44,justifyContent:'center',paddingHorizontal:8},error:{color:'#ff727b',fontSize:12}});
