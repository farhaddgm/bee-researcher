/* Native AudioWorklet in three engines and two emulated mobile profiles.
 * Oscillator input tests the real worklet/resampler, not a PCM fallback.
 * Physical microphone permission, audio routes and OS interruption remain
 * separate device acceptance checks.
 */
import assert from 'node:assert/strict';
import {startVirtualAudio,resumeNativeWorklets} from './voice_browser_audio.mjs';
const stopVirtualAudio=await startVirtualAudio();
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {chromium,firefox,webkit,devices} from 'playwright';
const server=createServer((req,res)=>{
  if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<!DOCTYPE html><button id="start">Start test</button>');return}
  if(!['/pcm.js','/pcm-worklet.js'].includes(req.url)){res.writeHead(404);res.end();return}
  res.setHeader('Content-Type','application/javascript');let source=readFileSync(new URL('../app/news_voice'+req.url,import.meta.url),'utf8');if(req.url==='/pcm-worklet.js')source=readFileSync(new URL('../app/news_voice/pcm.js',import.meta.url),'utf8').replace('export class PCMEncoder','class PCMEncoder')+'\n'+source.replace("import {PCMEncoder} from './pcm.js';",'');res.end(source);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base='http://127.0.0.1:'+server.address().port,results=[];
try{
  for(const [name,engine,profile] of [['Chromium',chromium,{}],['Firefox',firefox,{}],['WebKit',webkit,{}],
    ['Chromium Android emulation',chromium,devices['Pixel 7']],['WebKit iPhone emulation',webkit,devices['iPhone 13']]]){
    const browser=await engine.launch({headless:engine!==chromium,...(engine===chromium?{channel:'chromium',ignoreDefaultArgs:['--mute-audio'],args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']}: {})}),context=await browser.newContext(profile),page=await context.newPage(),errors=[];
    if(engine===chromium)await resumeNativeWorklets(browser);
    page.on('console',m=>console.log(name,m.text()));
    page.on('pageerror',e=>errors.push(e.message));
    try{
      page.setDefaultTimeout(15000);await page.goto(base);console.log('Testing native worklet:',name);
      await page.evaluate(()=>{
        document.querySelector('#start').onclick=()=>{
          window.done=(async()=>{
            const ctx=new AudioContext({sampleRate:48000});
            await Promise.race([ctx.resume(),new Promise((_,reject)=>setTimeout(()=>reject(Error('AudioContext did not resume')),3000))]);
            await Promise.race([ctx.audioWorklet.addModule(location.origin+'/pcm-worklet.js'),new Promise((_,reject)=>setTimeout(()=>reject(Error('Worklet module did not load')),5000))]);
            const processor=new AudioWorkletNode(ctx,'bee-pcm'),oscillator=ctx.createOscillator(),gain=ctx.createGain();
            oscillator.frequency.value=440;gain.gain.value=.25;
            const frames=[];let flush;
            const flushed=new Promise(resolve=>flush=resolve);
            processor.port.onmessage=event=>{if(event.data?.flushed)flush(new Int16Array(event.data.pcm));else frames.push(new Int16Array(event.data))};
            oscillator.connect(gain);gain.connect(processor);processor.connect(ctx.destination);oscillator.start();
            for(let wait=0;frames.length<5&&wait<60;wait++)await new Promise(resolve=>setTimeout(resolve,100));
            oscillator.stop();gain.disconnect();processor.port.postMessage('flush');
            const tail=await Promise.race([flushed,new Promise((_,reject)=>setTimeout(()=>reject(Error('No worklet flush')),2000))]);
            const maximum=frames.reduce((peak,frame)=>frame.reduce((p,x)=>Math.max(p,Math.abs(x)),peak),0);
            const rate=ctx.sampleRate;processor.disconnect();
            // Native output scheduling also has to reach its ended callback.
            const output=ctx;const source=output.createBufferSource();
            source.buffer=output.createBuffer(1,3200,16000);source.buffer.getChannelData(0).fill(.05);source.connect(output.destination);
            await new Promise((resolve,reject)=>{source.onended=resolve;source.start();setTimeout(()=>reject(Error('Playback did not finish')),2000)});
            await output.close();
            return {rate,frameSizes:frames.map(f=>f.length),tailSamples:tail.length,maximum,worklet:true,fallback:false,playback:true,closed:ctx.state==='closed'};
          })();
        };
      });
      await page.locator('#start').click();
      const result=await page.evaluate(()=>window.done);
      assert(result.worklet&&!result.fallback&&result.playback&&result.closed);
      assert(result.frameSizes.length>=3,name+' did not produce enough native PCM');
      assert(result.frameSizes.every(size=>size===3200));assert(result.tailSamples<3200);assert(result.maximum>1000);
      assert.deepEqual(errors,[]);results.push({name,...result,physicalDevice:false});
    }finally{await context.close();await browser.close()}
  }
  console.log(JSON.stringify({nativeWorkletMatrix:results,physicalDeviceAcceptance:'pending'},null,2));
}finally{stopVirtualAudio();server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
