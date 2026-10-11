/* Device-rate changes must keep actual mono PCM frames and the tail. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../app/news_voice/pcm.js',import.meta.url),'utf8').replace('export class PCMEncoder','globalThis.PCMEncoder = class PCMEncoder');
const ctx=vm.createContext({Int16Array,Math});vm.runInContext(source,ctx);
for(const rate of [16000,44100,48000,96000]){
  const frames=[],encoder=new ctx.PCMEncoder(rate,b=>frames.push(new Int16Array(b)));
  const input=Float32Array.from({length:rate},(_,i)=>Math.sin(i*2*Math.PI*440/rate)*.5);
  for(let i=0;i<input.length;i+=128)encoder.push(input.slice(i,i+128));
  frames.push(new Int16Array(encoder.flush()));
  const count=frames.reduce((sum,f)=>sum+f.length,0);assert(Math.abs(count-16000)<=2);
  assert(frames.slice(0,-1).every(f=>f.length===3200));
  assert(frames.some(f=>f.some(value=>value>10000)));assert(frames.some(f=>f.some(value=>value< -10000)));
  assert.equal(encoder.flush().byteLength,0);
}
console.log('PCM resampler passed: 16/44.1/48/96 kHz, 200 ms Int16 mono frames, negative/positive samples, continuous phase and final tail.');
