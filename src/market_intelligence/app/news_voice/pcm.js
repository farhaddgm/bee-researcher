/* Shared continuous resampler for AudioWorklet and legacy Web Audio capture. */
export class PCMEncoder {
  constructor(rate,emit){this.rate=rate;this.emit=emit;this.phase=0;this.last=0;this.frame=new Int16Array(3200);this.index=0}
  push(input){
    const ratio=this.rate/16000;
    for(const sample of input){
      while(this.phase<=1){
        const value=this.last+(sample-this.last)*this.phase;
        this.frame[this.index++]=Math.round(Math.max(-1,Math.min(1,value))*(value<0?32768:32767));
        if(this.index===this.frame.length){this.emit(this.frame.buffer);this.frame=new Int16Array(3200);this.index=0}
        this.phase+=ratio;
      }
      this.phase-=1;this.last=sample;
    }
  }
  flush(){const part=this.frame.slice(0,this.index);this.index=0;return part.buffer}
}
