/** Only coordinates in our embedded bundle. Never log raw stack text, symbols,
 * URLs, paths or exception messages. Symbolicate with the matching APK map. */
export function diagnosticErrorOrigin(error:unknown):{
  format:'hermes_bundle'|'unavailable';frames:{line:number;column:number}[];
}{
  const frames:{line:number;column:number}[]=[];
  try{
    if(error instanceof Error){
      const stack=error.stack;
      if(typeof stack==='string')for(const row of stack.slice(0,16384).split('\n').slice(1,33)){
        const match=/\(address at index\.android\.bundle:(\d{1,8}):(\d{1,10})\)\s*$/.exec(row);
        if(!match)continue;
        const line=Number(match[1]),column=Number(match[2]);
        if(line>0&&Number.isSafeInteger(column)&&column>=0)frames.push({line,column});
        if(frames.length===8)break;
      }
    }
  }catch{}
  return {format:frames.length?'hermes_bundle':'unavailable',frames};
}
