import {KeyboardSafeView} from '../KeyboardSafeView';
import {Keyboard} from 'react-native';
import React from 'react';
import { Modal, PanResponder, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import type { RemoteClient } from '../../api/client';
import type { ContinuousSettings, LlmModelState, VoiceState } from '../../api/types';
import type { useContinuousConversation } from '../../hooks/useContinuousConversation';
import { useThemedStyles, usePresentationStyle } from '../../styles/ThemeContext';
import { controlGlyphTypography, type ThemeColors } from '../../styles/theme';
import { LiveFullscreenSlider } from '../live-fullscreen/LiveFullscreenSlider';
import { GuidancePresetPicker } from './GuidancePresetPicker';
import { reorderReply } from '../../utils/continuousQueue';
import { applyNumericText, numericSettings, type NumericText } from '../../utils/continuousSettingsInput';
import {readableVoiceName} from '../../utils/voiceName';

type Props = { controller:ReturnType<typeof useContinuousConversation>; client:RemoteClient; unavailable:string; owner:object; showBar?:boolean; startUnavailable?:string; onResolveStart?:()=>Promise<unknown>; onForceContinuation?:()=>Promise<void>; playbackError?:string; onResumeResponse?:()=>Promise<void>; onAddStoryBeats?:()=>Promise<void> };

function DragHandle({move}:{move:(direction:number)=>void}) {
  const latest=React.useRef(move);latest.current=move;
  const responder=React.useMemo(()=>PanResponder.create({onStartShouldSetPanResponder:()=>true,
    onMoveShouldSetPanResponder:()=>true,onPanResponderRelease:(_e,g)=>{
      if(Math.abs(g.dy)>20) latest.current(g.dy>0?1:-1);
    }}),[]);
  return <View {...responder.panHandlers} accessibilityLabel="Drag up or down to move reply" style={{padding:14}}><Text style={{color:'#68D9FF'}}>Move</Text></View>;
}

export function ContinuousPanel({controller,client,unavailable,owner,showBar=true,startUnavailable='',onResolveStart,onForceContinuation,playbackError='',onResumeResponse,onAddStoryBeats}:Props) {
  const styles=useThemedStyles(createStyles, 'ContinuousPanel');
  const editorial=usePresentationStyle()==='editorial';
  const [voiceDetails,setVoiceDetails]=React.useState(false);
  const [queueOpen,setQueueOpen]=React.useState(false);
  const [open,setOpen]=React.useState(false),[advanced,setAdvanced]=React.useState(false);
  const [draft,setDraft]=React.useState<ContinuousSettings | null>(null),[dirty,setDirty]=React.useState(false);
  const dirtyFields=React.useRef(new Set<keyof ContinuousSettings>());
  const [text,setText]=React.useState(''),[editing,setEditing]=React.useState('');
  const [models,setModels]=React.useState<LlmModelState | null>(null),[modelError,setModelError]=React.useState('');
  const [chooser,setChooser]=React.useState<'provider'|'model'|null>(null);
  const [numericText,setNumericText]=React.useState<NumericText>({});
  const [inputError,setInputError]=React.useState('');
  const [voices,setVoices]=React.useState<VoiceState|null>(null);
  const [voicePickerOpen,setVoicePickerOpen]=React.useState(false),[voiceSearch,setVoiceSearch]=React.useState('');
  const voiceOwner=React.useRef(owner);voiceOwner.current=owner;
  const loadVoices=()=>{const currentOwner=owner;void client.voices().then(value=>{if(voiceOwner.current===currentOwner)setVoices(value);})
    .catch(()=>{if(voiceOwner.current===currentOwner)setInputError('Could not load desktop voices. Check NC and refresh.');});};
  React.useEffect(()=>{setVoices(null);},[owner]);
  React.useEffect(()=>{if(open && draft?.speak_user_messages && !voices)loadVoices();},[open,draft?.speak_user_messages,owner]);
  const [forcing,setForcing]=React.useState(false);
  const forceInFlight=React.useRef(false);
  const arming=React.useRef(0);
  const state=controller.state;
  React.useEffect(()=>{arming.current++;dirtyFields.current.clear();setOpen(false);setDraft(null);setDirty(false);setText('');setEditing('');setModels(null);setChooser(null);setNumericText({});setInputError('');setVoicePickerOpen(false);setVoiceSearch('');},[owner]);
  React.useEffect(()=>{if(state?.settings)setDraft(value=>dirty&&value?{
    ...state.settings!, ...Object.fromEntries([...dirtyFields.current].map(key=>[key,value[key]])),
  }:state.settings!);},[state?.settings,dirty]);
  const update=(patch:Partial<ContinuousSettings>)=>{Object.keys(patch).forEach(key=>dirtyFields.current.add(key as keyof ContinuousSettings));setDraft(value=>value?{...value,...patch}:value);setDirty(true);setInputError('');setNumericText(values=>Object.fromEntries(Object.entries(values).filter(([key])=>!(key in patch))));};
  const run=async(kind:string,payload:Record<string,unknown>={})=>{
    if(kind==='pause'||kind==='stop')arming.current++;
    setInputError('');
    try {await controller.command(kind,payload);}
    catch(error){setInputError(error instanceof Error?error.message:'Command failed. Try again.');throw error;}
  };
  const quiet=(work:Promise<unknown>)=>{void work.catch(()=>undefined);};
  const button=(label:string,action:()=>void,disabled=false,selected=false,tone:'default'|'advanced'|'save'='default',suffix?:React.ReactNode)=><Pressable
    key={label} accessibilityRole="button" accessibilityState={{disabled,selected}}
    accessibilityHint={tone==='save'?'Unsaved changes':undefined} disabled={disabled} onPress={action}
    style={({pressed})=>[styles.button,selected&&styles.selectedButton,tone==='advanced'&&!editorial&&styles.advancedButton,
      tone==='save'&&(editorial?styles.editorialSaveButton:styles.saveButton),pressed&&!disabled&&styles.pressed,disabled&&styles.disabled]}>
    <Text style={[styles.buttonText,selected&&styles.selectedButtonText,tone==='advanced'&&!editorial&&styles.advancedButtonText,
      tone==='save'&&styles.saveButtonText]}>{label}{suffix ? <> {suffix}</> : null}</Text>
  </Pressable>;
  const save=async()=>{
    if(!draft)return false;
    if(draft.speak_user_messages && !draft.user_voice){setInputError('Choose a desktop user voice first.');return false;}
    let settings:ContinuousSettings;
    try {settings=applyNumericText(draft,numericText);}
    catch(error){setInputError(error instanceof Error?error.message:'Check numeric settings.');return false;}
    const patch=Object.fromEntries([...dirtyFields.current].map(key=>[key,settings[key]])) as Partial<ContinuousSettings>;
    if(!state?.structured_auto_reply_supported)delete patch.speak_guidance_and_example;
    if(!state?.guidance_strength_supported)delete patch.guidance_strength;
    await run('settings',{settings:patch});
    dirtyFields.current.clear();setNumericText({});setInputError('');setDirty(false);return true;
  };
  const arm=async(kind:'start'|'resume')=>{
    const attempt=++arming.current;
    if(dirty && !await save())return;
    if(attempt!==arming.current)return;
    await run(kind);
  };
  const forceContinuation=async()=>{
    if(forceInFlight.current || !onForceContinuation)return;
    forceInFlight.current=true;setForcing(true);setInputError('');
    const attempt=++arming.current;
    try {
      if(dirty && !await save())return;
      if(attempt!==arming.current)return;
      await run('pause');
      if(arming.current!==attempt+1)return;
      const pausedAttempt=arming.current;
      await onForceContinuation();
      if(pausedAttempt!==arming.current)return;
      await run('force_continue');
    } catch(error) {setInputError(error instanceof Error?error.message:'Force continuation failed. Try again.');}
    finally {forceInFlight.current=false;setForcing(false);}
  };
  const loadModels=()=>{setModelError('');void client.llmModels().then(setModels).catch(()=>setModelError('Could not load models. Check the provider on the desktop.'));};
  const queue=state?.queue || [];
  const provider=models?.providers.find(p=>p.id===draft?.provider_id);
  const namedVoices=React.useMemo(()=>{
    const counts=new Map<string,number>();
    return (voices?.items||[]).map(voice=>{
      const name=readableVoiceName(voice.label);
      const count=(counts.get(name)||0)+1;
      counts.set(name,count);
      return {...voice,name:count===1?name:`${name} (${count})`};
    });
  },[voices]);
  const selectedVoice=namedVoices.find(voice=>voice.id===draft?.user_voice);
  const presets=state?.guidance_presets || [];
  const presetsSupported=typeof draft?.use_premade==='boolean' && presets.length>0;
  const structuredRepliesSupported=state?.structured_auto_reply_supported===true;
  const blocked=Boolean(unavailable || !state?.owned);
  const storyComplete=state?.story_complete===true;
  const status=storyComplete?'Story finished':controller.readingUser?'Reading your reply aloud...':state?.state==='delay'?`Next reply in ${(state.remaining_seconds||0).toFixed(1)} s`
    :state?.state==='generating'?'Creating Auto-Reply...':state?.state==='waiting'?(playbackError?'Playback interrupted — open Controls':'Waiting for the whole reply to finish')
    :state?.state==='suspended'?'Connection interrupted — reconnecting':state?.state || 'Off';
  const presetControls=draft?<>
            <View style={styles.voiceChoice}>
              <View style={styles.voiceChoiceText}><Text style={styles.voiceName}>Use premade</Text><Text style={styles.note}>Choose a direction for the story.</Text></View>
              <Switch accessibilityLabel="Use premade" value={Boolean(draft.use_premade)} disabled={blocked||controller.busy||!presetsSupported}
                onValueChange={use_premade=>update({use_premade})}/>
            </View>
            {!presetsSupported?<Text style={styles.note}>Update and restart NC desktop to use guidance presets. Your custom guidance remains available.</Text>:null}
  </>:null;
  const voiceControls=draft?<>
            {!editorial ? <Text style={styles.label}>User-message voice (Continuous Mode only)</Text> : null}
            {button(`Read user messages: ${draft.speak_user_messages?'On':'Off'}`,()=>update({speak_user_messages:!draft.speak_user_messages}),blocked||draft.mode==='off'||draft.speak_user_messages===undefined)}
            {editorial ? button(voiceDetails ? 'Hide voice options' : 'Voice options',()=>setVoiceDetails(value=>!value)) : null}
            <View style={editorial && !voiceDetails && !(draft.speak_user_messages && !draft.user_voice) ? {display:'none'} : {gap:12}}>
            <View style={styles.voiceChoice}>
              <View style={styles.voiceChoiceText}><Text style={styles.voiceName}>Also read guidance and example</Text><Text style={styles.note}>AI Guided can read all three sections. Chat still shows only the automated user response.</Text></View>
              <Switch accessibilityLabel="Also read guidance and example" value={Boolean(draft.speak_guidance_and_example)}
                disabled={blocked||controller.busy||!structuredRepliesSupported||draft.mode!=='ai_guided'||!draft.speak_user_messages}
                onValueChange={speak_guidance_and_example=>update({speak_guidance_and_example})}/>
            </View>
            {!structuredRepliesSupported?<Text style={styles.note}>Update and restart NC desktop to use three-part Auto-Reply and optional guidance speech.</Text>:null}
            {draft.speak_user_messages?<>
              <Text style={styles.label}>Desktop user voice</Text>
              <View style={styles.voiceChoice}>
                <View style={styles.voiceChoiceText}><Text style={styles.voiceHint}>Selected voice</Text><Text numberOfLines={2} style={styles.voiceName}>{selectedVoice?.name||'Choose a voice'}</Text></View>
                {button(voicePickerOpen?'Close voices':'Change voice',()=>{setVoicePickerOpen(value=>!value);setVoiceSearch('');},blocked)}
              </View>
              {voicePickerOpen?<View style={styles.voicePicker}>
                <TextInput accessibilityLabel="Search desktop voices" placeholder="Search voices" placeholderTextColor={styles.note.color}
                  style={styles.input} value={voiceSearch} onChangeText={setVoiceSearch}/>
                <ScrollView nestedScrollEnabled style={styles.voiceList} keyboardShouldPersistTaps="handled">
                  {namedVoices.filter(voice=>voice.name.toLowerCase().includes(voiceSearch.trim().toLowerCase())).map(voice=><Pressable
                    key={voice.id} accessibilityRole="button" accessibilityState={{selected:draft.user_voice===voice.id,disabled:blocked}}
                    disabled={blocked} onPress={()=>{update({user_voice:voice.id});setVoicePickerOpen(false);setVoiceSearch('');}}
                    style={[styles.voiceRow,draft.user_voice===voice.id&&styles.selected]}>
                    <Text numberOfLines={2} style={styles.voiceName}>{voice.name}</Text><Text style={styles.voiceMarker}>{draft.user_voice===voice.id?'Selected':'Use'}</Text>
                  </Pressable>)}
                  {!namedVoices.length?<Text style={styles.note}>No desktop voices available.</Text>:null}
                </ScrollView>
                {button('Refresh desktop voices',loadVoices,blocked)}
              </View>:null}
              {!draft.user_voice?<Text style={styles.warning}>Choose a desktop voice for the automated user.</Text>:null}
            </>:null}
            <Text style={styles.note}>Uses NC's active desktop TTS provider and your selected voice (including Chatterbox voice references). Audio streams to the phone; the assistant reply waits until user-message playback finishes. Your character voices stay unchanged. Pause or Stop cancels user speech. Ordinary messages and one-off Send Next stay silent.</Text>
            </View>
            <View style={editorial && draft.mode!=='simple' && !advanced ? {display:'none'} : {gap:8}}>
            <Text style={styles.label}>Default Auto Reply</Text><TextInput accessibilityLabel="Default Auto Reply" style={styles.input} value={draft.default_reply} maxLength={8000} onChangeText={default_reply=>update({default_reply})} />
            </View>
  </>:null;
  return <>
    {showBar ? <Pressable accessibilityRole="button" accessibilityLabel={editorial ? `Continuous Mode. ${status}. Open controls.` : undefined}
      onPress={()=>setOpen(true)} style={[styles.launch,editorial&&{minHeight:44,paddingVertical:6}]}>
      {editorial ? <Text numberOfLines={1} style={[styles.note,styles.launchInfo]}>Continuous · {status}</Text>
        : <View style={styles.launchInfo}><Text style={styles.title}>Continuous Mode</Text><Text numberOfLines={1} style={styles.note}>{status}</Text></View>}
      <Text style={styles.openControls}>Controls</Text>
    </Pressable> : null}
    <Modal onShow={Keyboard.dismiss} visible={open} animationType="slide" onRequestClose={()=>setOpen(false)}>
      <KeyboardSafeView active={open} style={styles.screen}>
        <View style={styles.header}><Text style={[styles.heading,editorial&&{fontFamily:'serif',fontWeight:'400'}]}>Continuous conversation</Text>{button('Done',()=>setOpen(false))}</View>
        <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={styles.content}>
          {!editorial ? <Text style={styles.note}>The next user message is sent after the entire character reply finishes speaking.</Text> : null}
          {editorial && draft ? <View style={styles.row}>{(['off','simple','ai_guided'] as const).map(mode=>button(mode==='ai_guided'?'AI Guided':mode==='simple'?'Simple':'Off',()=>update({mode}),blocked,draft.mode===mode))}</View> : null}
          {unavailable?<Text style={styles.warning}>{unavailable}</Text>:null}
          {state && !state.owned?<Text style={styles.warning}>Another phone owns these controls.</Text>:null}
          {inputError?<Text accessibilityLiveRegion="polite" style={styles.warning}>{inputError}</Text>:null}
          {controller.error?<Text accessibilityLiveRegion="polite" style={styles.warning}>{controller.error}</Text>:null}
          {playbackError?<View style={styles.card}>
            <Text accessibilityLiveRegion="polite" style={styles.warning}>{playbackError}</Text>
            {onResumeResponse?button('Resume response',()=>quiet(onResumeResponse().catch(error=>{
              setInputError(error instanceof Error?error.message:'Could not resume audio. Try again.');
            })),blocked||controller.busy||forcing):null}
          </View>:null}
          <View style={[styles.card,editorial&&{paddingVertical:8,paddingHorizontal:0,gap:8}]}><Text style={styles.title}>{status}</Text>{!editorial || state?.reason ? <Text style={styles.note}>{state?.reason || `${state?.completed_turns||0} completed continuous turns`}</Text> : null}
            {storyComplete && onAddStoryBeats ? button('Add more beats',()=>{setOpen(false);void onAddStoryBeats();},blocked) : null}
            <View style={styles.row}>
              {!editorial || !state || state.state==='stopped' ? button('Start',()=>quiet(arm('start')),blocked||storyComplete||Boolean(startUnavailable)||controller.busy||!draft||draft.mode==='off') : null}
              {!editorial || (state && !['stopped','paused'].includes(state.state)) ? button('Pause',()=>quiet(run('pause')),blocked) : null}
              {!editorial || state?.state==='paused' || state?.state==='suspended' ? button('Resume',()=>quiet(arm('resume')),blocked||storyComplete||Boolean(startUnavailable)||controller.busy||!draft||draft.mode==='off') : null}
              {button('Stop',()=>quiet(run('stop')),blocked)}
              {button(forcing?'Continuing...':'Force continuation',()=>quiet(forceContinuation()),blocked||storyComplete||controller.busy||forcing||Boolean(startUnavailable)||!draft||draft.mode==='off'||!state?.force_continuation_supported||!onForceContinuation)}
            </View>
            {!editorial ? <Text style={styles.note}>Pause and Stop leave the current character reply to finish. Force continuation stops audio, creates a fresh reply and keeps Continuous Mode running. Queued messages are kept.</Text> : null}
            {!state&&!unavailable?<Text style={styles.note}>Loading Continuous Mode controls...</Text>:null}
            {startUnavailable?<><Text style={styles.warning}>{startUnavailable}</Text>{onResolveStart?button('Stop microphone',()=>quiet(onResolveStart().catch(error=>{setInputError(error instanceof Error?error.message:'Could not stop microphone.');})),blocked||controller.busy):null}</>:null}
            {draft?.mode==='off'?<Text style={styles.note}>Choose Simple or AI Guided below to enable Start and Resume.</Text>:dirty?<Text style={styles.note}>Start and Resume save your edited settings before continuing.</Text>:null}

          </View>
          {draft?<View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:8,gap:10}]}>
            {!editorial ? <><Text style={styles.title}>Mode</Text><View style={styles.row}>{(['off','simple','ai_guided'] as const).map(mode=>button(mode==='ai_guided'?'AI Guided':mode==='simple'?'Simple':'Off',()=>update({mode}),blocked,draft.mode===mode))}</View></> : null}
            {!editorial ? voiceControls : null}
            <Text style={styles.label}>Auto-Reply Guidance</Text>
            <Text style={styles.note}>{editorial?'Guide the next story beat.':structuredRepliesSupported?'AI Guided prepares direction, a sample assistant answer and an automated user response. The main chat uses all three for its next reply; only the user response appears in chat.':'Direct the next story beat. AI Guided writes a short instruction to the storyteller.'}</Text>
            {structuredRepliesSupported&&draft.mode==='ai_guided'&&draft.max_output_tokens<256?<>
              <Text style={styles.warning}>Your saved Auto-Reply budget is {draft.max_output_tokens} tokens. Three sections may be cut off. Try 512 tokens; your current setting is kept until you save.</Text>
              {button('Use 512 tokens',()=>update({max_output_tokens:512}),blocked||controller.busy)}
            </>:null}
            {!editorial ? presetControls : null}
            {draft.use_premade?<>
              <GuidancePresetPicker presets={presets} value={draft.guidance_preset} disabled={blocked||controller.busy}
                onChange={guidance_preset=>update({guidance_preset})}/>
              <Text style={styles.note}>Switch off Use premade to return to your saved custom guidance.</Text>
            </>:<TextInput accessibilityLabel="Auto-Reply Guidance" editable={!blocked&&!controller.busy} multiline scrollEnabled style={[styles.input,styles.multiline,editorial&&{height:100,maxHeight:100}]} value={draft.guidance} maxLength={8000} onChangeText={guidance=>update({guidance})} placeholder="Advance one meaningful event, show its consequences, and avoid repeating completed beats." placeholderTextColor={styles.note.color}/>}
            {state?.guidance_strength_supported ? <View pointerEvents={blocked||controller.busy?'none':'auto'}>
              <LiveFullscreenSlider label="Guidance strength" value={draft.guidance_strength ?? 60}
                minimum={0} maximum={100} step={1} onChange={guidance_strength=>update({guidance_strength})}/>
              {editorial ? <View style={{flexDirection:'row',justifyContent:'space-between'}}><Text style={styles.note}>Story led</Text><Text style={styles.note}>Director</Text></View>
                : <Text style={styles.note}>0% Story led · 25% Gentle · 50% Balanced · 75% Strong · 100% Director</Text>}
              {!editorial ? <Text style={styles.note}>Save settings to apply to the next automated reply. Current speech finishes normally.</Text> : null}
            </View> : null}
            {!editorial ? <Text style={styles.note}>Save settings to apply guidance in AI Guided mode. Queued replies take priority; Simple mode and the default fallback use Default Auto Reply.</Text> : null}
            {editorial ? presetControls : null}
            {editorial ? voiceControls : null}
            {button(advanced?'Hide advanced settings':editorial?'Model & advanced':'Advanced Auto-Reply settings',()=>setAdvanced(!advanced),false,false,'advanced')}
            {advanced?<>
              <Text style={styles.label}>Auto-Reply LLM</Text><View style={styles.row}>{button('Same as Main',()=>update({separate_model:false}),blocked,!draft.separate_model)}{button('Separate model',()=>{update({separate_model:true});loadModels();},blocked,draft.separate_model)}</View>
              {draft.separate_model?<>
                {button(`Provider: ${provider?.label || draft.provider_id || 'Choose'}`,()=>{setChooser(chooser==='provider'?null:'provider');if(!models)loadModels();},blocked)}
                {chooser==='provider'?models?.providers.map(p=>button(p.label,()=>{update({provider_id:p.id,model_id:''});setChooser(null);},!p.available,p.id===draft.provider_id)):null}
                {button(`Model: ${provider?.models.find(m=>m.id===draft.model_id)?.label || 'Choose'}`,()=>setChooser(chooser==='model'?null:'model'),blocked)}
                {chooser==='model'?provider?.models.map(m=>button(m.label,()=>{update({model_id:m.id});setChooser(null);},false,m.id===draft.model_id)):null}
                {button('Refresh models',loadModels)}{modelError?<Text style={styles.warning}>{modelError}</Text>:null}
                <Text style={styles.note}>Uses an existing configured provider. The main conversation model selection stays unchanged.</Text>
              </>:null}
              <LiveFullscreenSlider label="Delay after reply" value={draft.delay_seconds} minimum={0} maximum={30} suffix=" s" onChange={delay_seconds=>update({delay_seconds})}/>
              <Text style={styles.label}>Maximum continuous turns</Text><View style={styles.row}>{[5,10,25,50,100,0].map(n=>button(n===0?'Unlimited':String(n),()=>update({max_turns:n}),blocked,draft.max_turns===n))}</View>
              {numericSettings.map(key=><View key={key}><Text style={styles.label}>{{max_turns:'Custom turn limit (0 = unlimited)',context_chars:'Context budget (characters)',recent_turns:'Recent messages',max_output_tokens:'Max Auto-Reply tokens',temperature:'Temperature'}[key]}</Text><TextInput accessibilityLabel={key} keyboardType="decimal-pad" style={styles.input} editable={!blocked&&!controller.busy} value={numericText[key] ?? String(draft[key])} onChangeText={value=>{dirtyFields.current.add(key);setNumericText(values=>({...values,[key]:value}));setDirty(true);setInputError('');}}/></View>)}
              {button(`Default fallback: ${draft.fallback?'On':'Off'}`,()=>update({fallback:!draft.fallback}),blocked)}
              <Text style={styles.note}>Guided mode pauses after three consecutive generation failures. Settings persist; running mode never resumes automatically after restarting.</Text>
            </>:null}
            {!editorial ? button(dirty?'Save settings':'Settings saved',()=>quiet(save()),!dirty||blocked||controller.busy,false,dirty?'save':'default') : null}
          </View>:null}
          {editorial ? button(`Queued replies (${queue.length})`,()=>setQueueOpen(value=>!value),false,false,'default',
            <Text style={controlGlyphTypography}>{queueOpen ? '−' : '+'}</Text>) : null}
          <View style={editorial && !queueOpen && !editing && !state?.pending_reply ? {display:'none'} : undefined}>
          <View style={styles.card}><Text style={styles.title}>Next user reply</Text><Text style={styles.note}>Queued messages take priority over automatic replies.</Text>
            <TextInput accessibilityLabel="Next user reply" multiline style={[styles.input,styles.multiline]} value={text} onChangeText={setText} maxLength={8000}/>
            <View style={styles.row}>{button(editing?'Save queued reply':'Queue',()=>quiet(run(editing?'edit':'add',{id:editing,text}).then(()=>{setText('');setEditing('');})),blocked||controller.busy||!text.trim(),false,editing&&text.trim()!==queue.find(item=>item.id===editing)?.text?'save':'default')}{editing?button('Cancel edit',()=>{setEditing('');setText('');}):null}</View>
            {queue.map((item,index)=><View key={item.id} style={styles.queueItem}><View style={styles.row}><DragHandle move={direction=>quiet(run('reorder',{ids:reorderReply(queue,item.id,index+direction)}))}/><Text style={styles.queueText}>{index+1}. {item.text}</Text></View><View style={styles.row}>{button('Edit',()=>{setEditing(item.id);setText(item.text);},blocked)}{button('Delete',()=>quiet(run('delete',{id:item.id})),blocked||controller.busy)}{button('Move up',()=>quiet(run('reorder',{ids:reorderReply(queue,item.id,index-1)})),blocked||controller.busy||index===0)}{button('Move down',()=>quiet(run('reorder',{ids:reorderReply(queue,item.id,index+1)})),blocked||controller.busy||index===queue.length-1)}</View></View>)}
            {!queue.length?<Text style={styles.note}>No queued replies.</Text>:null}
            <View style={styles.row}>{button('Send Next',()=>quiet(run('send_next')),blocked||dirty||controller.busy)}{button('Skip Next',()=>quiet(run('skip_next')),blocked||controller.busy)}{button('Clear queue',()=>quiet(run('clear')),blocked||controller.busy||!queue.length)}</View>
            {state?.pending_reply?<Text style={styles.note}>Next: {state.pending_reply}</Text>:null}
          </View>
          </View>
        </ScrollView>
        {editorial && draft ? <View style={{padding:16,gap:6}}>
          {button(dirty?'Save settings':'Settings saved',()=>quiet(save()),!dirty||blocked||controller.busy,false,'save')}
          <Text style={styles.note}>Applies to the next reply.</Text>
        </View> : null}
      </KeyboardSafeView>
    </Modal>
  </>;
}

const createStyles=(colors:ThemeColors)=>StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background,paddingTop:28},header:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',padding:16,gap:8},content:{padding:16,gap:16,paddingBottom:48},
  heading:{color:colors.text,fontWeight:'700',fontSize:20,flex:1},title:{color:colors.text,fontWeight:'700',fontSize:15},note:{color:colors.muted,fontSize:13,lineHeight:19},warning:{color:colors.warning,fontSize:14},
  launch:{padding:10,borderBottomWidth:1,borderColor:colors.border,flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:8},launchInfo:{flex:1,minWidth:0},openControls:{color:colors.accent,fontSize:13,fontWeight:'600'},card:{backgroundColor:colors.panel,borderWidth:1,borderColor:colors.border,borderRadius:14,padding:14,gap:12},row:{flexDirection:'row',flexWrap:'wrap',alignItems:'center',gap:8},
  voiceChoice:{backgroundColor:colors.panelAlt,borderWidth:1,borderColor:colors.border,borderRadius:10,padding:12,flexDirection:'row',alignItems:'center',gap:8},voiceChoiceText:{flex:1,minWidth:0},voiceHint:{color:colors.muted,fontSize:12},voiceName:{color:colors.text,fontSize:14,fontWeight:'600',flex:1},voicePicker:{gap:8},voiceList:{maxHeight:280},voiceRow:{minHeight:48,backgroundColor:colors.border,borderWidth:1,borderColor:colors.muted,borderRadius:8,padding:12,marginBottom:6,flexDirection:'row',alignItems:'center',gap:8},voiceMarker:{color:colors.text,fontSize:12,fontWeight:'700'},
  button:{minHeight:44,justifyContent:'center',alignItems:'center',backgroundColor:colors.border,borderWidth:1,borderColor:colors.muted,borderRadius:8,paddingHorizontal:12,paddingVertical:10},
  choiceButton:{backgroundColor:colors.border,borderColor:colors.muted},selected:{borderColor:colors.accent,backgroundColor:colors.accentSoft},
  selectedButton:{borderColor:colors.accent,backgroundColor:colors.accent},selectedButtonText:{color:colors.background},
  advancedButton:{backgroundColor:'#FFE1A6',borderColor:'#A56A14'},advancedButtonText:{color:'#4A320C'},
  saveButton:{backgroundColor:colors.ok,borderColor:colors.ok,shadowColor:colors.ok,shadowOpacity:.3,shadowRadius:8,shadowOffset:{width:0,height:0},elevation:3},saveButtonText:{color:colors.background},
  editorialSaveButton:{backgroundColor:colors.accent,borderColor:colors.accent,borderRadius:5},
  pressed:{opacity:.8},disabled:{opacity:.5},buttonText:{color:colors.text,fontWeight:'700',fontSize:13},
  label:{color:colors.textSecondary,fontSize:13,marginTop:6},input:{color:colors.text,backgroundColor:colors.backgroundElevated,borderWidth:1,borderColor:colors.border,borderRadius:8,padding:12,fontSize:15},multiline:{minHeight:90,textAlignVertical:'top'},queueItem:{borderTopWidth:1,borderColor:colors.border,paddingTop:10,gap:8},queueText:{color:colors.text,flex:1,lineHeight:21},
});
