import type {OrderedAnnouncement,OrderedNativeSnapshot} from './desktopOrderedProtocol';

export type OrderedProgressReport=Readonly<{version:1;replyId:string;firstSourceId:string;knownSegments:number;
  preparedUnits:number;completedSegments:number;playingSequence:number|null;finalSegments:number|null}>;

export class OrderedProgress {
  private replyId:string|null=null;
  private firstSourceId='';
  private readonly segments=new Map<number,{frames:number;total:number;completed:boolean}>();
  private playingSequence:number|null=null;
  /** Inputs are already validated retained ranges from a successful native ACK.
   * Never use announcement, download, elapsed-time or reader-release as heard evidence. */
  observe(rows:readonly OrderedAnnouncement[],native:OrderedNativeSnapshot):void{
    for(const {chunk:c,source} of rows){
      if(c.kind!=='speech')continue;
      if(c.replyId!==this.replyId){this.replyId=c.replyId;this.firstSourceId=c.sourceId;this.segments.clear();}
      const index=c.sequenceIndex!,prior=this.segments.get(index);
      this.segments.set(index,{frames:Math.max(prior?.frames??0,c.sourceRange.start+c.frameCount),
        total:source.plan.frames,completed:prior?.completed??false});
    }
    this.playingSequence=null;
    for(const s of native.sources){
      if(s.kind!=='speech'||s.replyId!==this.replyId)continue;
      const segment=this.segments.get(s.sequenceIndex!);if(!segment)continue;
      if(s.completed)segment.completed=true;
      else if(s.started)this.playingSequence=s.sequenceIndex;
    }
  }
  snapshot():OrderedProgressReport|null{
    if(!this.replyId)return null;
    let preparedUnits=0,completedSegments=0;
    for(let index=0;index<64;index++){
      const segment=this.segments.get(index);if(!segment)break;
      const fraction=Math.min(segment.frames/segment.total,1);preparedUnits+=fraction;if(fraction<1)break;
    }
    while(this.segments.get(completedSegments)?.completed)completedSegments++;
    return Object.freeze({version:1,replyId:this.replyId,firstSourceId:this.firstSourceId,
      knownSegments:Math.max(...this.segments.keys())+1,preparedUnits:Math.round(preparedUnits*10000)/10000,
      completedSegments,playingSequence:this.playingSequence,finalSegments:null});
  }
}
