import React,{useState} from 'react';
import {Keyboard,Modal,Pressable,ScrollView,StyleSheet,Switch,Text,TextInput,View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {KeyboardSafeView} from '../KeyboardSafeView';
import {SoundVolumeControl} from './SoundVolumeControl';
import {LiveFullscreenSlider} from '../live-fullscreen/LiveFullscreenSlider';
import {usePresentationStyle,useThemedStyles} from '../../styles/ThemeContext';
import {controlGlyphTypography, type ThemeColors} from '../../styles/theme';
import type {SoundAsset,SoundKind} from '../../api/soundscape';
import type {SoundscapeControls} from '../../hooks/useSoundscape';
import {makeSoundBatchPlan,soundBatchCategories,withSoundBatchDurationMs,type SoundBatchDraft} from '../../utils/soundBatch';

function SoundDetails({label,children}:{label:string;children:React.ReactNode}) {
  const editorial=usePresentationStyle()==='editorial';
  const styles=useThemedStyles(createStyles, 'SoundscapePanel');
  const [open,setOpen]=useState(false);
  if(!editorial)return <>{children}</>;
  return <><Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{expanded:open}}
    onPress={()=>setOpen(value=>!value)} style={[styles.row,{minHeight:48}]}>
    <Text style={styles.buttonText}>{label}</Text><Text style={[styles.buttonText,controlGlyphTypography]}>{open?'−':'+'}</Text>
  </Pressable>{open?children:null}</>;
}
const kinds=['ambience','music','effect'] as const;
const label=(kind:string)=>kind==='effect'?'Effects':kind.charAt(0).toUpperCase()+kind.slice(1);
export function SoundscapePanel({visible,onClose,sound,editAssetId}:{visible:boolean;onClose():void;sound:SoundscapeControls;editAssetId?:string}) {
  const styles=useThemedStyles(createStyles, 'SoundscapePanel'),insets=useSafeAreaInsets();
  const editorial=usePresentationStyle()==='editorial';
  const [overflowId,setOverflowId]=useState('');
  const [batchCategoriesOpen,setBatchCategoriesOpen]=useState(false);
  const [tab,setTab]=useState<'mix'|'library'|'generate'|'batch'>('mix');
  const [filter,setFilter]=useState<SoundKind|'all'>('all'),[query,setQuery]=useState('');
  const [categoryFilter,setCategoryFilter]=useState('All categories');
  const [kind,setKind]=useState<SoundKind>('ambience'),[prompt,setPrompt]=useState('');
  const [generationCategory,setGenerationCategory]=useState('Uncategorized');
  const [importCategory,setImportCategory]=useState('Uncategorized');
  const [batchCategory,setBatchCategory]=useState('Weather');
  const [batchCount,setBatchCount]=useState('12');
  const [batchRefiners,setBatchRefiners]=useState<Record<string,string>>({});
  const [batchDrafts,setBatchDrafts]=useState<SoundBatchDraft[]>([]);
  const [batchDraftKey,setBatchDraftKey]=useState('');
  const [batchDurationEdits,setBatchDurationEdits]=useState<Record<number,string>>({});
  const [batchConfirm,setBatchConfirm]=useState(false);
  const [duration,setDuration]=useState(30),[loop,setLoop]=useState(true),[instrumental,setInstrumental]=useState(true);
  const [confirm,setConfirm]=useState(false),[remove,setRemove]=useState<string|null>(null);
  const [draft,setDraft]=useState<SoundAsset|null>(null),[title,setTitle]=useState('');
  const [draftTags,setDraftTags]=useState('');
  const [generatedTags,setGeneratedTags]=useState('');
  const editedTarget=React.useRef('');
  const [generatedDetails,setGeneratedDetails]=useState<{kind:SoundKind;description:string;loop:boolean}|null>(null);
  const [failure,setFailure]=useState('');
  React.useEffect(()=>{if(!visible)void sound.stopPreview().catch(()=>undefined);},[visible]);
  React.useEffect(()=>{if(visible&&sound.available)void sound.refresh().catch(()=>undefined);},[visible,sound.available]);
  React.useEffect(()=>{
    if(!visible){editedTarget.current='';return;}
    if(!editAssetId||editedTarget.current===editAssetId)return;
    const asset=sound.assets.find(item=>item.id===editAssetId);if(!asset)return;
    editedTarget.current=editAssetId;setTab('library');setQuery('');setFilter('all');setCategoryFilter('All categories');
    setDraft({...asset,tags:[...asset.tags]});setDraftTags(asset.tags.join(', '));
  },[visible,editAssetId,sound.assets]);
  const run=(task:()=>Promise<unknown>)=>{setFailure('');void task().catch(error=>setFailure(error instanceof Error?error.message:'Sound operation failed.'));};
  const button=(text:string,action:()=>void,selected=false,disabled=false,allowBusy=false)=><Pressable accessibilityRole="button"
    accessibilityState={{selected,disabled:disabled||(sound.busy&&!allowBusy)}} disabled={disabled||(sound.busy&&!allowBusy)} onPress={action}
    style={[styles.button,selected&&styles.selected,(disabled||(sound.busy&&!allowBusy))&&styles.disabled]}><Text style={styles.buttonText}>{text}</Text></Pressable>;
  const toggle=(text:string,value:boolean,action:(value:boolean)=>void,disabled=false)=><View style={styles.row}>
    <Text style={styles.text}>{text}</Text><Switch accessibilityLabel={text} value={value} disabled={disabled||sound.busy||!sound.available} onValueChange={action}/></View>;
  const input=(text:string,value:string,change:(text:string)=>void,multi=false,maxLength=2000,numeric=false)=><View style={styles.field}>
    <Text style={styles.caption}>{text}</Text><TextInput accessibilityLabel={text} value={value} onChangeText={change}
      multiline={multi} maxLength={maxLength} keyboardType={numeric?'number-pad':'default'} style={[styles.input,multi&&styles.multiline]}/></View>;
  const state=sound.state;
  const categories=['All categories',...Array.from(new Set(sound.assets.map(asset=>asset.category||'Uncategorized'))).sort()];
  const generationActive=Boolean(sound.job&&['queued','submitting','converting','saving'].includes(sound.job.state));
  const batchRefiner=batchRefiners[batchCategory]||'';
  const batchSettingsKey=JSON.stringify([batchCategory.trim(),batchCount,batchRefiner]);
  const batchPlanCurrent=batchDraftKey===batchSettingsKey;
  const reviewedBatchDrafts=()=>batchDrafts.map((item,index)=>withSoundBatchDurationMs(item,
    batchDurationEdits[index]??String(Math.round(item.duration_seconds*1000))));
  const close=()=>{run(sound.stopPreview);onClose();};
  return <Modal visible={visible} animationType="slide" onRequestClose={close} onShow={Keyboard.dismiss}>
    <KeyboardSafeView style={styles.root} active={visible}>
      <View style={[styles.header,{paddingTop:insets.top+12}]}><Text style={[styles.title,editorial&&{fontFamily:'serif',fontWeight:'400'}]}>{editorial?({mix:'Soundscape',library:'Sound library',generate:'Generate sound',batch:'Batch create'}[tab]):'Soundscape'}</Text>
        <Pressable accessibilityRole="button" onPress={close} style={[styles.button,editorial&&{backgroundColor:'transparent',borderWidth:0,paddingHorizontal:4}]}><Text style={styles.buttonText}>Done</Text></Pressable></View>
      <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={[styles.content,editorial&&{gap:10,paddingTop:0},{paddingBottom:insets.bottom+32}]}>
        {!editorial?<Text style={styles.caption}>Background ambience and music for this conversation.</Text>:null}
        {!sound.available?<Text style={styles.error}>Connect an updated Android app and NC desktop to use Soundscape.</Text>:null}
        <View style={styles.wrap}>{(['mix','library','generate','batch'] as const).map(value=><React.Fragment key={value}>
          {editorial?<Pressable accessibilityRole="tab" accessibilityState={{selected:tab===value,disabled:sound.busy}}
            disabled={sound.busy} onPress={()=>setTab(value)}
            style={{minHeight:44,paddingHorizontal:10,justifyContent:'center',borderBottomWidth:tab===value?2:0,borderBottomColor:styles.buttonText.color}}>
            <Text style={[styles.buttonText,{fontWeight:'400'}]}>{label(value)}</Text>
          </Pressable>:button(label(value),()=>setTab(value),tab===value)}</React.Fragment>)}</View>
        {(failure||sound.error)?<Text accessibilityRole="alert" style={styles.error}>{failure||sound.error}</Text>:null}
        {!editorial||tab!=='mix'?<Text accessibilityLiveRegion="polite" style={styles.caption}>{sound.busy?'Working… ':''}{sound.status}</Text>:null}
        {tab==='mix'&&state?<>
          {editorial?<View style={[styles.row,{paddingVertical:8}]}>
            <View style={{flex:1,gap:4}}>{toggle('Soundscape',state.enabled,value=>run(()=>value?sound.resume():sound.change({enabled:false,paused:true})))}
              <Text accessibilityLiveRegion="polite" style={styles.caption}>{sound.busy?'Working…':sound.status}</Text></View>
            <Pressable accessibilityRole="button" disabled={!sound.available||(sound.busy&&(state.paused||!state.enabled))}
              onPress={()=>run(state.paused||!state.enabled?sound.resume:sound.pause)}
              style={{minHeight:44,paddingHorizontal:12,justifyContent:'center'}}>
              <Text style={styles.buttonText}>{state.paused||!state.enabled?'Resume':'Pause'}</Text>
            </Pressable>
          </View>:<>
          <View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
            {toggle('Soundscape',state.enabled,value=>run(()=>value?sound.resume():sound.change({enabled:false,paused:true})))}
            <SoundDetails label="Advanced audio">{toggle('Lower background during speech',state.duck_speech,value=>run(()=>sound.change({duck_speech:value})))}</SoundDetails>
            <View style={styles.wrap}>{button('Resume',()=>run(sound.resume),false,!sound.available)}{button('Pause',()=>run(sound.pause),false,!sound.available,true)}</View>
          </View>
          </>}
          {(['ambience','music'] as const).map(layer=><View key={layer} style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
            {editorial?<View style={styles.row}><Text style={[styles.heading,{fontFamily:'serif',fontWeight:'400'}]}>{label(layer)}</Text>
              {editorial?<Pressable accessibilityRole="button" onPress={()=>{setFilter(layer);setTab('library');}} style={{minHeight:44,justifyContent:'center',paddingHorizontal:4}}>
                <Text style={styles.buttonText}>Choose</Text></Pressable>:null}</View>:<Text style={styles.heading}>{label(layer)}</Text>}
            <Text style={styles.text}>{sound.assets.find(asset=>asset.id===state[layer].asset_id)?.title||'No sound selected'}</Text>
            <Text style={styles.caption}>{state[layer].muted?'Muted':state.paused?'Paused':Math.round(state[layer].volume*100)+'% volume'}</Text>
            {editorial?<SoundVolumeControl key={JSON.stringify([sound.volumeScope,layer,state[layer].asset_id,visible,sound.available])}
              label={label(layer)+' volume'} value={Math.round(state[layer].volume*100)} disabled={sound.busy||!sound.available}
              onApply={value=>sound.change({[layer]:{volume:value/100}})}/>:null}
            <SoundDetails label="Layer options">
            <View style={styles.wrap}>
              {!editorial?<>
              {button('− 5%',()=>run(()=>sound.change({[layer]:{volume:Math.max(0,state[layer].volume-.05)}})))}
              {button('+ 5%',()=>run(()=>sound.change({[layer]:{volume:Math.min(1,state[layer].volume+.05)}})))}
              </>:null}
              {!editorial?button('Choose',()=>{setFilter(layer);setTab('library');}):null}
              {button('Clear',()=>run(()=>sound.change({[layer]:{asset_id:null}})),false,!state[layer].asset_id)}
            </View>
            {toggle(`Mute ${layer}`,state[layer].muted,value=>run(()=>sound.change({[layer]:{muted:value}})))}
            </SoundDetails>
            {toggle(`Follow story — ${layer}`,state[layer].follow_story,value=>run(()=>sound.change({[layer]:{follow_story:value}})),!sound.followStoryAvailable)}
          </View>)}
          {sound.effectsAvailable&&state.effects?<View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
            <Text style={styles.heading}>Sound effects</Text>
            {toggle('Automatic sound effects',state.effects.enabled,value=>run(()=>sound.change({effects:{enabled:value}})))}
            <LiveFullscreenSlider label="Effect volume" value={Math.round(state.effects.volume*100)} minimum={0} maximum={100} step={5}
              onChange={value=>run(()=>sound.change({effects:{volume:value/100}}))}/>
            {toggle('Mute sound effects',state.effects.muted,value=>run(()=>sound.change({effects:{muted:value}})))}
            <Text style={styles.caption}>One matching tagged effect per spoken reply. Late or unavailable effects are omitted; speech never waits.</Text>
          </View>:null}
          {editorial?<SoundDetails label="Advanced audio">{toggle('Lower background during speech',state.duck_speech,value=>run(()=>sound.change({duck_speech:value})))}</SoundDetails>:null}
          <SoundDetails label="About story matching"><Text style={styles.caption}>{sound.followStoryAvailable?'Follow story matches the scene and current Story Plan beat to saved sounds. A cloud chat model may refine the choice in the background; speech never waits. Add descriptive titles and tags for better matches.':'Automatic scene selection needs the updated NC desktop. Choose saved backgrounds manually until it is available.'}</Text></SoundDetails>
        </>:null}
        {tab==='library'?<>
          <SoundDetails label="Import sounds">
          <View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}><Text style={styles.heading}>Import your sounds</Text>
            <View style={styles.wrap}>{kinds.map(value=><React.Fragment key={value}>{button(label(value),()=>setKind(value),kind===value)}</React.Fragment>)}</View>
            {input('Import category',importCategory,setImportCategory,false,64)}
            {button('Choose audio files',()=>run(()=>sound.importFiles(kind,importCategory)),false,!sound.available||!importCategory.trim())}
            {(sound.importResults??[]).map((result,index)=><Text key={index} style={result.state==='failed'?styles.error:styles.caption}>{result.name} · {result.state}</Text>)}
            <Text style={styles.caption}>MP3, M4A, AAC or Ogg/Opus. Up to 100 files, 100 MB and 30 minutes each. Desktop folder import includes subfolders. Filename tags are suggestions: preview and edit them.</Text>
          </View>
          </SoundDetails>
          <View style={styles.wrap}>{(['all',...kinds] as const).map(value=><React.Fragment key={value}>
            {button(label(value),()=>setFilter(value),filter===value)}</React.Fragment>)}{button('Refresh',()=>run(sound.refresh))}</View>
          {input('Search library',query,setQuery,false,120)}
          <Text style={styles.caption}>Categories</Text>
          <View style={styles.wrap}>{categories.map(value=><React.Fragment key={value}>{button(value,()=>setCategoryFilter(value),categoryFilter===value)}</React.Fragment>)}</View>
          {sound.assets.filter(asset=>(filter==='all'||asset.kind===filter)
            &&(categoryFilter==='All categories'||(asset.category||'Uncategorized')===categoryFilter)
            &&(`${asset.title} ${asset.category||''} ${asset.description} ${asset.tags.join(' ')}`).toLowerCase().includes(query.toLowerCase())).map(asset=><View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]} key={asset.id}>
            <Text style={styles.heading}>{asset.title}</Text><Text style={styles.caption}>{label(asset.kind)} · {asset.category||'Uncategorized'} · {Math.round(asset.duration_ms/1000)} seconds{asset.loop?' · Loop':''} · {Math.round((asset.gain??1)*100)}% sound volume</Text>
            {asset.description&&(!editorial||overflowId===asset.id)?<Text style={styles.text}>{asset.description}</Text>:null}
            {asset.tags.length&&(!editorial||overflowId===asset.id)?<Text style={styles.caption}>{asset.tags.join(' · ')}</Text>:null}
            {!editorial||overflowId===asset.id?<Text style={styles.caption}>{asset.discarded?'Excluded from automatic selection':asset.tags.length?'Tagged for scene matching':'Add content tags to enable automatic selection'}</Text>:null}
            {draft?.id===asset.id?<>
              {input('Title',draft.title,title=>setDraft({...draft,title}),false,120)}
              {input('Description',draft.description,description=>setDraft({...draft,description}),true)}
              {input('Category',draft.category,category=>setDraft({...draft,category}),false,64)}
              {input('Tags (comma separated)',draftTags,setDraftTags,false,650)}
              <LiveFullscreenSlider label="Sound volume" value={Math.round(draft.gain*100)} minimum={0} maximum={100} step={5}
                onChange={value=>setDraft(previous=>previous?.id===asset.id?{...previous,gain:value/100}:previous)}/>
              {toggle('Loop sound',draft.loop,loop=>setDraft({...draft,loop}))}
              <View style={styles.wrap}>{button('Save',()=>run(async()=>{await sound.updateAsset(asset,{title:draft.title,description:draft.description,kind:draft.kind,category:draft.category,gain:draft.gain,tags:draftTags.split(',').map(v=>v.trim()).filter(Boolean),loop:draft.loop});setDraft(null);} ))}{button('Cancel',()=>setDraft(null))}</View>
            </>:<View style={styles.wrap}>
              {asset.kind==='effect'?<>
                {button(sound.previewId===asset.id&&!sound.previewPaused?'Pause':'Play',()=>run(()=>sound.review(asset)),false,!sound.available)}
                {sound.previewId===asset.id?button('Stop review',()=>run(sound.stopPreview)):null}
              </> : button(sound.previewId===asset.id?'■ Stop preview':'▶ Preview',()=>run(()=>sound.preview(asset)),false,!sound.available)}
              {asset.kind!=='effect'?button('Use '+label(asset.kind),()=>run(async()=>{await sound.useAsset(asset);setTab('mix');}),false,!state||Boolean(asset.discarded)):null}
              {editorial?button(overflowId===asset.id?'Less':'More',()=>setOverflowId(value=>value===asset.id?'':asset.id)):null}
              {!editorial||overflowId===asset.id?<>
              {sound.contextAvailable?button(asset.discarded?'Restore sound':'Discard',()=>run(()=>sound.discardAsset(asset,!asset.discarded))):null}
              {button('Edit',()=>{setDraft({...asset,category:asset.category||'Uncategorized',gain:asset.gain??1,tags:[...asset.tags]});setDraftTags(asset.tags.join(', '));})}
              {button('Remove',()=>setRemove(asset.id))}              </>:null}
            </View>}
            {remove===asset.id?<><Text style={styles.error}>Delete this sound from the library? Saved stories keep their own copy.</Text>
              <View style={styles.wrap}>{button('Delete sound',()=>run(async()=>{await sound.removeAsset(asset);setRemove(null);} ))}{button('Keep',()=>setRemove(null))}</View></>:null}
          </View>)}
          {!sound.assets.length?<Text style={styles.caption}>Your library is empty. Import audio or generate a sound.</Text>:null}
        </>:null}
        {tab==='generate'?<View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
          <Text style={styles.heading}>Generate with ElevenLabs</Text><Text style={styles.caption}>Uses the ElevenLabs configuration on your desktop. Each Generate or Regenerate is a new paid provider request.</Text>
          <View style={styles.wrap}>{kinds.map(value=><React.Fragment key={value}>{button(label(value),()=>{setKind(value);setDuration(value==='music'?60:30);setInstrumental(true);setLoop(value!=='effect');setConfirm(false);},kind===value,generationActive)}</React.Fragment>)}</View>
          {input('Describe the sound',prompt,setPrompt,true,4100)}
          <Text style={styles.caption}>Duration</Text><View style={styles.wrap}>{(kind==='music'?[30,60,120,180]:[.5,5,10,20,30]).map(value=><React.Fragment key={value}>
            {button(`${value}s`,()=>setDuration(value),duration===value,generationActive)}</React.Fragment>)}</View>
          <SoundDetails label="Advanced generation options">
          {toggle('Loop on playback',loop,setLoop)}
          {input('Category',generationCategory,setGenerationCategory,false,64)}
          {kind==='music'?toggle('Instrumental only',instrumental,setInstrumental):null}
          {kind==='music'?<Text style={styles.caption}>Music repeats may have an audible transition. Preview your track before choosing it.</Text>:null}
          </SoundDetails>
          {confirm?<><Text style={styles.text}>Send this request to ElevenLabs?</Text><View style={styles.wrap}>
            {button('Generate now',()=>run(async()=>{setConfirm(false);await sound.generate({kind,prompt,duration_seconds:duration,loop,instrumental});setGeneratedDetails({kind,description:prompt.slice(0,2000),loop});setTitle(prompt.slice(0,80));}),false,generationActive||!prompt.trim()||!sound.available)}
            {button('Cancel',()=>setConfirm(false))}</View></>:button(sound.job?'Regenerate':'Generate',()=>setConfirm(true),false,generationActive||!prompt.trim()||!sound.available)}
          {sound.job?<><Text accessibilityLiveRegion="polite" style={styles.text}>Generation: {sound.job.state}</Text>
            {sound.job.error?<Text style={styles.error}>{sound.job.error}</Text>:null}
            {sound.job.state==='ready'&&sound.job.preview?<>
              {button(sound.previewId===sound.job.id?'■ Stop preview':'▶ Preview',()=>run(()=>sound.preview(sound.job!.preview!)))}
              {input('Save as',title,setTitle,false,120)}
              {input('Content tags (comma separated)',generatedTags,setGeneratedTags,false,650)}
              {button('Save to library',()=>run(()=>sound.saveGenerated({title,...(generatedDetails||{kind,description:prompt.slice(0,2000),loop}),category:generationCategory,gain:1,tags:generatedTags.split(',').map(v=>v.trim()).filter(Boolean)})),false,!title.trim()||!generationCategory.trim())}
            </>:null}
            <View style={styles.wrap}>{generationActive?button('Cancel generation',()=>run(sound.cancelGenerated)):sound.job.state!=='saved'?button('Discard',()=>run(sound.discardGenerated)):null}</View>
            <Text style={styles.caption}>Preview and Save use the same audio. Saving does not change your current background.</Text>
          </>:null}
        </View>:null}
        {tab==='batch'?<>
          <View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
            <Text style={styles.heading}>Batch Create</Text>
            <Text style={styles.caption}>{editorial?'Draft 1–12 sounds, then review before generating.':'Choose 1–12 sounds, shape the prompts, and review each request before sending it to ElevenLabs. Ambient and Music are saved as background sounds; other categories are effects.'}</Text>
            {editorial?<Pressable accessibilityRole="button" accessibilityLabel="Batch category" accessibilityState={{expanded:batchCategoriesOpen}}
              onPress={()=>setBatchCategoriesOpen(value=>!value)} style={styles.input}>
              <Text style={styles.text}>{batchCategory} <Text style={controlGlyphTypography}>{batchCategoriesOpen?'−':'+'}</Text></Text></Pressable>:null}
            {!editorial||batchCategoriesOpen?<>
            <View style={styles.wrap}>{soundBatchCategories.map(value=><React.Fragment key={value}>
              {button(value,()=>{setBatchCategory(value);setBatchCategoriesOpen(false);setBatchDrafts([]);setBatchDurationEdits({});setBatchConfirm(false);},batchCategory===value)}</React.Fragment>)}</View>
            </>:null}
            <SoundDetails label="Custom category">
            {input('Category name',batchCategory,value=>{setBatchCategory(value);setBatchDrafts([]);setBatchConfirm(false);},false,64)}
            </SoundDetails>
            {input('Number of sounds',batchCount,value=>{setBatchCount(value);setBatchConfirm(false);},false,2,true)}
            {input('Category prompt refiner',batchRefiner,value=>{setBatchRefiners(previous=>({...previous,[batchCategory]:value}));setBatchConfirm(false);},true,1000)}
            <Text style={styles.caption}>This direction is added to every drafted prompt in this category. Switching categories keeps each note while this screen stays open.</Text>
            {button(`Draft ${batchCount||'?'} ${batchCategory} sounds`,()=>run(async()=>{
              const drafts=makeSoundBatchPlan(batchCategory,Number(batchCount),batchRefiner);
              setBatchDrafts(drafts);setBatchDurationEdits({});setBatchDraftKey(batchSettingsKey);setBatchConfirm(false);
            }),false,!batchCategory.trim())}
            {batchDrafts.length?<>
              <Text style={styles.caption}>Review all {batchDrafts.length} sounds. One paid request is sent per sound. Titles and category make saved sounds findable for story cues.</Text>
              {!batchPlanCurrent?<Text style={styles.error}>Category settings changed. Draft again before generating.</Text>:null}
              {batchDrafts.map((draft,index)=><View key={index} style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
                <Text style={styles.heading}>{index+1}. {draft.title}</Text>
                <SoundDetails label="Edit name & prompt">
                {input('Sound name',draft.title,value=>setBatchDrafts(previous=>previous.map((item,i)=>i===index?{...item,title:value}:item)),false,120)}
                {input('ElevenLabs prompt',draft.prompt,value=>setBatchDrafts(previous=>previous.map((item,i)=>i===index?{...item,prompt:value}:item)),true,4100)}
                </SoundDetails>
                {input('Duration (ms)',batchDurationEdits[index]??String(Math.round(draft.duration_seconds*1000)),value=>{
                  setBatchDurationEdits(previous=>({...previous,[index]:value}));setBatchConfirm(false);
                },false,6,true)}
                <Text style={styles.caption}>{draft.kind==='music'?'Music: 30000, 60000, 120000 or 180000 ms.':'Effects and ambience: 500–30000 ms.'}</Text>
              </View>)}
              {batchConfirm?<>
                <Text style={styles.error}>Start {batchDrafts.length} separate paid ElevenLabs requests? Submitted requests may still be charged if cancelled.</Text>
                <View style={styles.wrap}>{button('Generate all',()=>run(async()=>{const drafts=reviewedBatchDrafts();setBatchConfirm(false);await sound.startBatch(batchCategory,drafts);}),false,!sound.available||!batchPlanCurrent)}
                  {button('Keep editing',()=>setBatchConfirm(false))}</View>
              </>:button('Review cost and generate',()=>run(async()=>{reviewedBatchDrafts();setBatchConfirm(true);}),false,!sound.available||!batchPlanCurrent||Boolean(sound.batch&&!sound.batch.stopped&&sound.batch.items.some(item=>!['saved','failed','cancelled','outcome_unknown'].includes(item.state))))}
            </>:null}
          </View>
          {sound.batch?<View style={[styles.card,editorial&&{paddingHorizontal:0,paddingVertical:12,gap:8}]}>
            <Text style={styles.heading}>{sound.batch.category} batch</Text>
            <Text style={styles.caption}>{sound.batch.items.filter(item=>item.state==='saved').length} of {sound.batch.items.length} saved · {sound.batch.stopped?'Stopped':'In progress'}</Text>
            {sound.batch.items.map((item,index)=><View key={item.request_id} style={styles.row}>
              <Text style={styles.text}>{index+1}. {item.title}</Text><Text style={styles.caption}>{item.state}</Text>
              {item.error?<Text style={styles.error}>{item.error}</Text>:null}
            </View>)}
            <View style={styles.wrap}>{button('Refresh batch',()=>run(sound.refreshBatch))}
              {sound.batch.items.some(item=>item.state==='save_failed')?button('Retry saving',()=>run(sound.retryBatchSaves)):null}
              {!sound.batch.stopped&&sound.batch.items.some(item=>!['saved','failed','cancelled','outcome_unknown'].includes(item.state))
                ?button('Stop remaining',()=>run(sound.cancelBatch)):null}</View>
          </View>:null}
        </>:null}
      </ScrollView>
    </KeyboardSafeView>
  </Modal>;
}
const createStyles=(colors:ThemeColors)=>StyleSheet.create({
  root:{flex:1,backgroundColor:colors.background},header:{paddingHorizontal:20,paddingBottom:14,flexDirection:'row',alignItems:'center',justifyContent:'space-between'},
  title:{color:colors.text,fontSize:24,fontWeight:'700'},heading:{color:colors.text,fontSize:18,fontWeight:'700'},text:{color:colors.text,fontSize:16,flexShrink:1},
  caption:{color:colors.muted,fontSize:14,lineHeight:21},error:{color:colors.danger,fontSize:15},content:{padding:20,gap:16},card:{backgroundColor:colors.panel,borderRadius:18,padding:18,gap:14,borderWidth:1,borderColor:colors.border},
  row:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',gap:12},wrap:{flexDirection:'row',flexWrap:'wrap',gap:10},field:{gap:6},
  button:{minHeight:46,paddingHorizontal:16,paddingVertical:12,borderRadius:12,backgroundColor:colors.panelAlt,borderWidth:1,borderColor:colors.border,justifyContent:'center'},
  selected:{borderColor:colors.accent,backgroundColor:colors.accentSoft},buttonText:{color:colors.accent,fontSize:15,fontWeight:'600'},disabled:{opacity:.45},
  input:{color:colors.text,borderWidth:1,borderColor:colors.border,borderRadius:12,padding:14,minHeight:50,fontSize:16,backgroundColor:colors.background},multiline:{minHeight:110,textAlignVertical:'top'},
});
