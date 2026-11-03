import * as Crypto from 'expo-crypto';
import * as FileSystem from 'expo-file-system/legacy';
import type {SoundBatch,SoundBatchStore} from './soundBatch';

type RecordOnDisk={revision:number;batch:SoundBatch};
type StoredSlot={record:RecordOnDisk;slot:number};

/** Two alternating private files retain the previous request IDs if a write is interrupted. */
export function soundBatchStorage(scope:()=>string):SoundBatchStore{
  let fixedScope='';
  let tail:Promise<void>=Promise.resolve();
  const serialized=<T,>(operation:()=>Promise<T>):Promise<T>=>{
    const result=tail.then(operation,operation);
    tail=result.then(()=>undefined,()=>undefined);
    return result;
  };
  const paths=async()=>{
    fixedScope ||= scope();
    if(!fixedScope||!FileSystem.documentDirectory)throw new Error('Sound batch storage is unavailable. Connect to NC first.');
    const digest=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,fixedScope);
    return [0,1].map(slot=>`${FileSystem.documentDirectory}nc-sound-batch-${digest}.${slot}.json`);
  };
  const entries=async()=>{
    const filenames=await paths();
    const found:StoredSlot[]=[];
    let existing=0;
    for(let slot=0;slot<filenames.length;slot++){
      const filename=filenames[slot]!;
      if(!(await FileSystem.getInfoAsync(filename)).exists)continue;
      existing++;
      try{
        const value=JSON.parse(await FileSystem.readAsStringAsync(filename)) as RecordOnDisk;
        if(value&&Number.isSafeInteger(value.revision)&&value.revision>0
          &&value.batch?.version===1&&Array.isArray(value.batch.items))found.push({record:value,slot});
      }catch{ /* The other slot can still contain the last durable request IDs. */ }
    }
    if(existing&&!found.length)throw new Error('Saved sound batch is damaged. No new paid requests were sent.');
    return found.sort((a,b)=>b.record.revision-a.record.revision);
  };
  return {
    read:()=>serialized(async()=>{
      const found=await entries();
      return found[0]?.record.batch||null;
    }),
    write:batch=>serialized(async()=>{
      const filenames=await paths();
      const found=await entries();
      const revision=(found[0]?.record.revision||0)+1;
      const slot=found[0]?1-found[0].slot:revision%2;
      await FileSystem.writeAsStringAsync(filenames[slot]!,JSON.stringify({revision,batch}));
    }),
  };
}
