/* A local null sink supplies a genuine audio render thread in Linux CI.
 * Only oscillator/fake-device input is used. No OS microphone is accessed.
 */
import {spawnSync,spawn} from 'node:child_process';
import {mkdirSync,existsSync} from 'node:fs';
export async function startVirtualAudio(){
  const runtime='/tmp/bee-voice-pulse-'+process.pid;mkdirSync(runtime,{mode:0o700});
  process.env.PULSE_RUNTIME_PATH=runtime;process.env.PULSE_SERVER='unix:'+runtime+'/native';
  const result=spawnSync('pulseaudio',['--daemonize=yes','--exit-idle-time=-1','--load=module-null-sink sink_name=bee_voice',
    '--load=module-native-protocol-unix socket='+runtime+'/native auth-anonymous=1'],{encoding:'utf8',timeout:10000});
  if(result.status!==0)throw Error('Virtual audio backend is required for native Worklet tests');
  const display=spawn('Xvfb',[':101','-ac','-screen','0','1280x1024x24','-nolisten','tcp'],{stdio:'ignore'});process.env.DISPLAY=':101';
  for(let i=0;!existsSync('/tmp/.X11-unix/X101')&&i<50;i++)await new Promise(resolve=>setTimeout(resolve,100));
  if(!existsSync('/tmp/.X11-unix/X101'))throw Error('Virtual display did not start');
  console.log('Native browser audio backend: isolated PulseAudio null sink');
  return ()=>{display.kill();spawnSync('pulseaudio',['--kill'],{timeout:5000,stdio:'ignore'})};
}

export async function resumeNativeWorklets(browser){
  // Playwright 1.55 detaches unknown "worklet" targets while they are still
  // waiting for the debugger. Resume only that real Chromium target; do not
  // substitute processors, PCM, timing, or the application capture path.
  const root=await browser.newBrowserCDPSession();
  await root.send('Target.setDiscoverTargets',{discover:true});
  root.on('Target.targetCreated',async({targetInfo})=>{
    if(targetInfo.type!=='worklet')return;
    try{
      const {sessionId}=await root.send('Target.attachToTarget',{targetId:targetInfo.targetId,flatten:false});
      await root.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id:1,method:'Runtime.runIfWaitingForDebugger'})});
    }catch(_){/* A closed page can destroy the target before attachment. */}
  });
  return root;
}
