export type ChatScrollEvent = 'scroll' | 'layout' | 'content' | 'bottom' | 'prepend'
  | 'pinch_stop' | 'reading_offset' | 'reading_index' | 'reading_estimate' | 'drag' | 'drag_end' | 'momentum_end';
type Sample = [number, ChatScrollEvent, number, number, number, number, number];
export type ChatScrollReport = {revision: 'chat-scroll-v1'; events: Sample[]};

/** Numeric-only, bounded evidence. This observer never moves the list or sets React state. */
export class ChatScrollTrace {
  private samples: Sample[] = [];
  private lastSampleAt = -Infinity;
  private movement: {y:number; at:number; direction:number; reversals:number} | null = null;
  private lastReportAt = -Infinity;
  constructor(private emit: (report:ChatScrollReport)=>void, private now:()=>number=()=>performance.now()) {}
  reset():void { this.samples=[]; this.movement=null; this.lastSampleAt=-Infinity; }
  record(kind:ChatScrollEvent, y:number, height:number, viewport:number, flags:number, dataRevision:number):void {
    if (![y,height,viewport,flags,dataRevision].every(Number.isFinite)) return;
    const now=this.now();
    if (kind!=='scroll' || now-this.lastSampleAt>=50) {
      this.samples.push([Math.round(now),kind,Math.round(y),Math.round(height),Math.round(viewport),flags,dataRevision]);
      if(this.samples.length>48)this.samples.shift();
      this.lastSampleAt=now;
    }
    // Bits 1 and 2 mean a user drag/fling or pinch is active. They are not idle jumps.
    if (flags&3) { this.movement=null; return; }
    if(kind!=='scroll')return;
    const previous=this.movement;
    if(!previous || now-previous.at>4000) {this.movement={y,at:now,direction:0,reversals:0};return;}
    const delta=y-previous.y;
    if(Math.abs(delta)<64)return;
    const direction=Math.sign(delta);
    const reversals=previous.reversals+(previous.direction && previous.direction!==direction?1:0);
    this.movement={y,at:now,direction,reversals};
    if(reversals<2 || now-this.lastReportAt<60000)return;
    this.lastReportAt=now;this.movement.reversals=0;
    try {this.emit({revision:'chat-scroll-v1',events:this.samples.map(sample=>[...sample] as Sample)});} catch { /* Diagnostics cannot break scrolling. */ }
  }
}
