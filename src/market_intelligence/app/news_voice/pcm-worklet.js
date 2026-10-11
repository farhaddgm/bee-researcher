/* Continuous device sample rate -> 16kHz signed mono PCM; bounded frames. */
import {PCMEncoder} from './pcm.js';
class BeePCM extends AudioWorkletProcessor {
  constructor(){super();this.encoder=new PCMEncoder(sampleRate,b=>this.port.postMessage(b,[b]));this.port.onmessage=e=>{if(e.data==='flush'){const part=this.encoder.flush();this.port.postMessage({flushed:true,pcm:part},[part])}}}
  process(inputs){
    const input=inputs[0]?.[0];if(input)this.encoder.push(input);
    return true;
  }
}
registerProcessor('bee-pcm',BeePCM);
