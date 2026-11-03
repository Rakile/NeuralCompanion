// Room-only durable state and a short cross-process critical section.
import {openSync,closeSync,writeFileSync,renameSync,unlinkSync,mkdirSync,readFileSync,statSync,appendFileSync} from 'node:fs';
import {dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
const held=new Set();
const sleeper=new Int32Array(new SharedArrayBuffer(4));
function windowsSharingError(error) {
  return process.platform==='win32' && ['EPERM','EACCES','EBUSY'].includes(error.code);
}
function removeOwnedLock(path,deadline) {
  for(;;) {
    try {unlinkSync(path);return;}
    catch(error) {
      if(error.code==='ENOENT')return;
      if(!windowsSharingError(error) || Date.now()>=deadline)throw error;
      Atomics.wait(sleeper,0,0,10);
    }
  }
}
export function withRoomStateLock(path,callback) {
  if(held.has(path)) return callback();
  const deadline=Date.now()+2000;
  let handle;
  mkdirSync(dirname(path),{recursive:true});
  while(handle===undefined) {
    let acquired;
    try {
      acquired=openSync(path,'wx');
      writeFileSync(acquired,JSON.stringify({pid:process.pid}));
      handle=acquired;
    }
    catch(error) {
      if(acquired!==undefined) {
        try {closeSync(acquired);} finally {removeOwnedLock(path,deadline);}
        throw error;
      }
      // Windows can report a delete-pending lock as EPERM rather than EEXIST.
      // Retry only within the same bounded acquisition deadline.
      if(error.code!=='EEXIST' && !windowsSharingError(error)) throw error;
      try {
        const owner=JSON.parse(readFileSync(path,'utf8'));
        let alive=true;
        try { process.kill(Number(owner.pid),0); } catch(error) { if(error.code==='ESRCH') alive=false; }
        if(!alive && Date.now()-statSync(path).mtimeMs>1000) {unlinkSync(path);continue;}
      }catch{} // A creator may still be writing the lock owner.
      if(Date.now()>=deadline) throw Error('Discord room state is busy; retry the action.',{cause:error});
      Atomics.wait(sleeper,0,0,10);
    }
  }
  held.add(path);
  try {return callback();}
  finally {held.delete(path);try {closeSync(handle);} finally {removeOwnedLock(path,Date.now()+2000);}}
}
export function atomicWriteJson(path,value) {
  mkdirSync(dirname(path),{recursive:true});
  const temporary=path+'.'+process.pid+'.'+randomUUID()+'.tmp';
  try {
    writeFileSync(temporary,JSON.stringify(value,null,2),'utf8');
    const deadline=Date.now()+2000;
    for(;;) {
      try {renameSync(temporary,path);break;}
      catch(error) {
        // A Python UI reader may briefly hold the destination without delete
        // sharing on Windows. Keep the old complete file until replacement wins.
        if(!windowsSharingError(error) || Date.now()>=deadline)throw error;
        Atomics.wait(sleeper,0,0,10);
      }
    }
  }
  finally {try {unlinkSync(temporary);}catch(error){if(error.code!=='ENOENT')throw error;}}
}
export function appendRoomEvent(path,event) {
  mkdirSync(dirname(path),{recursive:true});
  appendFileSync(path,JSON.stringify(event)+'\n','utf8');
}
