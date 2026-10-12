/* ElevenLabs through Bee; no provider key or device speech fallback. */
(() => {
  'use strict';
  const copy=window.BeeNewsChatI18n,t=copy.t;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
  const translated=(tag,key,cls)=>{const n=node(tag,t(key),cls);n.dataset.voiceKey=key;return n};
  const button=(key,fn)=>{const b=translated('button',key,'btn');b.type='button';b.addEventListener('click',fn);return b};
  const field=(key,n)=>{const l=node('label');l.append(translated('span',key),n);n.setAttribute('aria-label',t(key));n.dataset.voiceLabel=key;return l};
  async function api(path,options={}){
    const cookie=document.cookie.split('; ').find(v=>v.startsWith('research_bee_user_csrf='));const r=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.method?{'X-CSRF-Token':cookie?decodeURIComponent(cookie.split('=').slice(1).join('=')):''}:{}),...(options.headers||{})}});
    const data=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(typeof data.detail==='string'?data.detail:'voice_failed');e.status=r.status;throw e}return data;
  }
  let caps={enabled:false,voices:[]},workspace=null,epoch=0,recording=null,stream=null,streamReject=null,currentAudio=null,previewAudio=null;
  const players=new Set(),keys=new Map(),assets=new Map();
  const errorState=e=>e?.status===429?'voiceBudget':['voice_unconfigured','voice_disabled'].includes(e?.message)?'voiceNotConfigured':e?.message==='voice_full_recording_unavailable'?'audioMissing':'voiceError';
  async function configure(aid){
    if(workspace!==aid){clear();workspace=aid;caps={enabled:false,voices:[]}}
    const generation=epoch,data=await api('/user/api/voice/capabilities?assistant_id='+aid);
    if(generation===epoch&&workspace===aid)caps=data;return data;
  }
  function prepareInput(){const context=new AudioContext();return {context,resumed:context.resume()}}
  function detachMic(r){clearTimeout(r.timer);r.track?.getTracks().forEach(n=>n.stop());r.source?.disconnect();r.worklet?.disconnect();r.context?.close().catch(()=>{})}
  function stopRecording(graceful=false){
    const r=recording;if(!r)return;recording=null;
    if(graceful&&r.ws?.readyState===WebSocket.OPEN){
      r.stopping=true;r.track?.getTracks().forEach(n=>n.stop());r.source?.disconnect();
      if(r.worklet){r.worklet.port.postMessage('flush');setTimeout(()=>{if(!r.stopSent&&r.ws.readyState===WebSocket.OPEN){r.stopSent=true;r.ws.send(JSON.stringify({type:'stop'}));detachMic(r)}},150)}
      else{r.stopSent=true;r.ws.send(JSON.stringify({type:'stop'}));detachMic(r)}
    }
    else {detachMic(r);r.ws?.close();if(r.id)api('/user/api/voice-sessions/'+r.id+'/stop',{method:'POST',body:'{}',keepalive:true}).catch(()=>{})}
  }
  function stop(){epoch++;previewAudio?.stop();previewAudio=null;stopRecording();stream?.close();stream=null;streamReject?.(new Error('voice_cancelled'));streamReject=null;if(currentAudio){currentAudio.pause();currentAudio=null}}
  function clear(){stop();for(const p of players){p.pause();p.removeAttribute('src');p.load()}players.clear();keys.clear();assets.clear();caps={enabled:false,voices:[]}}
  async function dictate(language,onText,onState,options={}){
    stop();const stamp=epoch;
    if(!caps.enabled||!options.cid||!navigator.mediaDevices?.getUserMedia||!window.AudioContext){onState('voiceNotConfigured');return}
    const r={context:options.prepared?.context};recording=r;onState('voicePreparing');
    try{
      r.context=r.context||new AudioContext();const resumed=options.prepared?.resumed||r.context.resume();
      r.track=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
      if(stamp!==epoch){detachMic(r);return}
      await Promise.race([resumed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('audio_autoplay')),2000))]);
      let worklet=false;
      if(r.context.audioWorklet&&window.AudioWorkletNode){try{worklet=await Promise.race([r.context.audioWorklet.addModule('/assets/news-voice/pcm-worklet.js').then(()=>true),new Promise(resolve=>setTimeout(()=>resolve(false),2000))])}catch(_){}}
      let PCMEncoder;if(!worklet){const module=await import('/assets/news-voice/pcm.js');PCMEncoder=module.PCMEncoder}
      if(stamp!==epoch){detachMic(r);return}
      const session=await api('/user/api/conversations/'+options.cid+'/voice-sessions',{method:'POST',body:JSON.stringify({
        idempotency_key:crypto.randomUUID(),language,transfer_consent:true,consent_version:'voice-1',
        retain_user_audio_for_save:Boolean(options.retain),continuous:Boolean(options.continuous),keyterms:options.keyterms||[]})});
      r.id=session.id;
      if(stamp!==epoch){detachMic(r);api('/user/api/voice-sessions/'+r.id+'/stop',{method:'POST',body:'{}'}).catch(()=>{});return}
      r.ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/user/api/voice-sessions/'+r.id+'/input');
      r.ws.binaryType='arraybuffer';let sequence=0,finalSequence=0,done=false;
      r.ws.onopen=()=>{
        if(stamp!==epoch){r.ws.close();return}
        r.ws.send(JSON.stringify({ticket:session.ticket}));
        r.source=r.context.createMediaStreamSource(r.track);
        if(worklet)r.worklet=new AudioWorkletNode(r.context,'bee-pcm');
        else{
          r.worklet=r.context.createScriptProcessor(4096,1,1);
          const encoder=new PCMEncoder(r.context.sampleRate,pcm=>r.worklet.port.onmessage?.({data:pcm}));
          r.worklet.port={onmessage:null,postMessage:message=>{if(message==='flush')r.worklet.port.onmessage?.({data:{flushed:true,pcm:encoder.flush()}})}};
          r.worklet.onaudioprocess=event=>encoder.push(event.inputBuffer.getChannelData(0));
        }
        r.worklet.port.onmessage=event=>{
          if((recording!==r&&!r.stopping)||r.ws.readyState!==WebSocket.OPEN||r.stopSent)return;
          if(r.ws.bufferedAmount>64000){stopRecording();onState('voiceError');return}
          const flushed=event.data?.flushed,pcm=new Uint8Array(flushed?event.data.pcm:event.data);if(pcm.length){const frame=new Uint8Array(pcm.length+4);new DataView(frame.buffer).setUint32(0,sequence++,true);frame.set(pcm,4);r.ws.send(frame)}if(flushed){r.stopSent=true;r.ws.send(JSON.stringify({type:'stop'}));detachMic(r)}
        };
        r.source.connect(r.worklet);r.worklet.connect(r.context.destination);r.timer=setTimeout(()=>{if(recording===r)stopRecording(true)},Math.max(1,session.max_input_seconds-1)*1000);onState('listening');
      };
      r.ws.onmessage=event=>{
        if(stamp!==epoch)return;const data=JSON.parse(event.data);
        if(data.type==='partial')options.onPartial?.(data.text);
        if(data.type==='final'&&data.sequence>finalSequence){finalSequence=data.sequence;onText(data.text);options.onPartial?.('');if(options.continuous)stopRecording(true)}
        if(data.type==='done'){done=true;if(recording===r)recording=null;detachMic(r);onState('voiceReview');options.onDone?.(data)}
        if(data.type==='error'){stopRecording();onState(errorState({message:data.error_code}));done=true}
      };
      r.ws.onerror=()=>{if(stamp===epoch){stopRecording();onState('voiceError')}};
      r.ws.onclose=()=>{detachMic(r);if(recording===r)recording=null;if(stamp===epoch&&!done)onState('voiceError')};
    }catch(e){if(recording===r)recording=null;detachMic(r);if(stamp===epoch)onState(errorState(e))}
  }
  function trackPlayer(asset,audio){
    for(const p of players)if(!p.isConnected){p.pause();p.removeAttribute('src');players.delete(p)}players.add(audio);
    let last=null,ranges=[];
    audio.addEventListener('play',()=>{previewAudio?.stop();previewAudio=null;if(currentAudio&&currentAudio!==audio)currentAudio.pause();currentAudio=audio;last=audio.currentTime});
    audio.addEventListener('seeking',()=>last=null);audio.addEventListener('seeked',()=>last=audio.currentTime);
    audio.addEventListener('timeupdate',()=>{const current=audio.currentTime;if(!audio.paused&&!audio.seeking&&last!==null&&current>last&&current-last<=1.5)ranges.push([last,current]);last=current});
    const acknowledge=()=>{if(!audio.currentTime)return;const snapshot=ranges;ranges=[];
      api('/user/api/voice-audio/'+asset.id+'/playback',{method:'POST',body:JSON.stringify({played_seconds:Math.min(600,audio.currentTime),played_ranges:snapshot.slice(-100),interrupted:!audio.ended&&audio.currentTime<audio.duration})}).catch(()=>{})};
    audio.addEventListener('pause',acknowledge);audio.addEventListener('ended',acknowledge);
  }
  async function livePreview(asset,stamp,onState){
    if(!window.AudioContext)return null;
    const ctx=new AudioContext(),controller=new AbortController(),sources=new Set();let at=0,first=null,position=0,stopped=false;const intervals=[];
    const out={position:()=>{let played=0;for(const [start,end,offset] of intervals){if(ctx.currentTime<start)break;played=offset+Math.min(end-start,Math.max(0,ctx.currentTime-start))}return played},stop:(interrupted=true)=>{
      if(stopped)return;stopped=true;controller.abort();const played=out.position();for(const source of sources){try{source.stop()}catch(_){}}
      ctx.close().catch(()=>{});if(played>0)api('/user/api/voice-audio/'+asset.id+'/playback',{method:'POST',body:JSON.stringify({played_seconds:Math.min(600,played),played_ranges:[[0,Math.min(600,played)]],interrupted:interrupted&&played+0.1<position})}).catch(()=>{})
    }};
    try{await Promise.race([ctx.resume(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('audio_autoplay')),1000))]);if(ctx.state!=='running'){out.stop();return null}}catch(_){out.stop();return null}
    previewAudio=out;
    out.done=(async()=>{
      try{
        const response=await fetch('/user/api/voice-audio/'+asset.id+'/stream',{credentials:'same-origin',signal:controller.signal});
        if(!response.ok)throw new Error('voice_failed');
        const reader=response.body.getReader(),decoder=new TextDecoder();let pending='',sequence=0;
        while(!stopped&&stamp===epoch){
          const chunk=await reader.read();if(chunk.done)break;pending+=decoder.decode(chunk.value,{stream:true});
          if(pending.length>4000000)throw new Error('voice_failed');
          let newline;
          while((newline=pending.indexOf('\n'))>=0&&!stopped){
            const line=pending.slice(0,newline);pending=pending.slice(newline+1);if(!line)continue;const frame=JSON.parse(line);
            if(frame.error)throw new Error(frame.error);if(frame.done)return;
            if(frame.sequence!==++sequence)throw new Error('voice_failed');
            const bytes=Uint8Array.from(atob(frame.pcm),c=>c.charCodeAt(0));if(!bytes.length||bytes.length%2||bytes.length>16000)throw new Error('voice_failed');
            while(!stopped&&at-ctx.currentTime>1)await new Promise(r=>setTimeout(r,50));
            if(stopped||stamp!==epoch)return;
            const samples=bytes.length/2,buffer=ctx.createBuffer(1,samples,16000),values=buffer.getChannelData(0),view=new DataView(bytes.buffer);
            for(let i=0;i<samples;i++)values[i]=view.getInt16(i*2,true)/32768;
            const source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);sources.add(source);source.onended=()=>sources.delete(source);
            at=Math.max(at,ctx.currentTime+.04);if(first===null)first=at;intervals.push([at,at+samples/16000,position]);source.start(at);at+=samples/16000;position+=samples/16000;onState('speaking');
          }
        }
      }catch(e){if(!stopped&&stamp===epoch)onState(errorState(e));out.stop()}
    })();
    return out;
  }
  function player(asset,parent,onState=()=>{}){
    const box=node('div',undefined,'voice-player');box.dataset.audioId=asset.id;
    const audio=node('audio');audio.controls=true;audio.preload='none';audio.src=asset.content_url;audio.setAttribute('aria-label',asset.title||t('playAnswer'));trackPlayer(asset,audio);
    const speed=node('select');for(const value of [.75,1,1.25,1.5,2]){const option=node('option',value+'×');option.value=value;speed.append(option)}speed.value='1';speed.addEventListener('change',()=>audio.playbackRate=Number(speed.value));
    const download=translated('a','downloadAudio','btn');download.href='/user/api/voice-audio/'+asset.id+'/download';
    box.append(audio,field('playbackSpeed',speed),download);
    const timing=asset.metadata.timing||[];
    if(timing.length&&timing.map(x=>x.text).join('')===asset.metadata.spoken_text){
      const transcript=node('p',undefined,'voice-timed-text'),words=[];let current=null;
      for(const cue of timing){if(!current||/\s/.test(cue.text)){current={start:cue.start,end:cue.end,span:node('span',cue.text)};words.push(current);transcript.append(current.span)}else{current.span.textContent+=cue.text;current.end=cue.end}}
      box.append(transcript);audio.addEventListener('timeupdate',()=>{for(const word of words)word.span.classList.toggle('voice-active-word',audio.currentTime>=word.start&&audio.currentTime<word.end)});
    }
    if(asset.saved_at){
      const marks=node('div',undefined,'voice-bookmarks');
      const drawMarks=()=>{marks.replaceChildren();for(const mark of asset.metadata.bookmarks||[]){const b=button('playAnswer',()=>{audio.currentTime=mark.seconds;audio.play().catch(()=>onState('audioAutoplay'))});b.textContent=mark.label;delete b.dataset.voiceKey;const action=button('draftAction',async()=>{try{const manifest=await api('/user/api/voice-audio/'+asset.id+'/manifest'),segment=manifest.segments.find(s=>s.start_ms<=mark.seconds*1000&&s.end_ms>=mark.seconds*1000);window.dispatchEvent(new CustomEvent('bee:action-draft',{detail:{title:mark.label,text:segment?.text||segment?.submitted_question||mark.label,publication_id:manifest.publication_id,assistant_id:manifest.assistant_id,conversation_id:manifest.conversation_id}}))}catch(e){onState(errorState(e))}});marks.append(b,action)}};
      const bookmark=button('bookmarkAudio',async()=>{const label=window.prompt(t('bookmarkLabel'));if(!label?.trim())return;try{Object.assign(asset,await api('/user/api/voice-audio/'+asset.id+'/bookmarks',{method:'POST',body:JSON.stringify({version:asset.version,seconds:Math.min(audio.currentTime,asset.duration_seconds),label:label.trim().slice(0,180)})}));drawMarks()}catch(e){onState(errorState(e))}});
      const remove=button('audioDelete',async()=>{if(!window.confirm(t('audioDeleteConfirm')))return;try{await api('/user/api/voice-audio/'+asset.id,{method:'DELETE'});audio.pause();audio.removeAttribute('src');players.delete(audio);box.remove();window.dispatchEvent(new Event('bee:memory-saved'))}catch(e){onState(errorState(e))}});
      const details=node('details');details.append(translated('summary','audioTranscript'));let loaded=false;
      details.addEventListener('toggle',async()=>{if(!details.open||loaded)return;try{const data=await api('/user/api/voice-audio/'+asset.id+'/manifest');if(!details.isConnected)return;loaded=true;for(const segment of data.segments){details.append(node('p',(segment.start_ms/1000).toFixed(1)+'–'+(segment.end_ms/1000).toFixed(1)+' s'));if(segment.speaker==='user')details.append(node('p',t('recognizedSpeech')+': '+segment.recognized_text),node('p',t('submittedQuestion')+': '+segment.submitted_question));else details.append(node('p',segment.spoken_text||segment.text));for(const cite of segment.citations||[]){if(cite.publication_id){const link=node('a',t('references'));link.href='/user/news/'+cite.publication_id;details.append(link)}}}}catch(e){onState(errorState(e))}});
      box.append(bookmark,remove,marks,details);drawMarks();
    }
    parent.append(box);return audio;
  }
  async function answer(row,onState,options={}){
    if(!caps.enabled){onState('voiceNotConfigured');return null}
    const voice=caps.voices.find(v=>v.key===options.voiceKey&&v.languages.includes(row.language))||caps.voices.find(v=>v.languages.includes(row.language));
    if(!voice){onState('voiceUnavailable');return null}
    stop();const stamp=epoch,key=row.id+':'+voice.key;
    try{
      let a=assets.get(key);onState('voicePreparing');
      const create=async(regenerate=false)=>{if(!keys.has(key)||regenerate)keys.set(key,crypto.randomUUID());return api('/user/api/chat-generations/'+row.id+'/audio',{method:'POST',body:JSON.stringify({idempotency_key:keys.get(key),voice_key:voice.key,transfer_consent:true,input_session_ids:options.inputs||[],regenerate})})};
      if(a&&!a.saved_at&&new Date(a.expires_at).getTime()<=Date.now())a=null;
      if(!a){try{a=await create()}catch(e){if(e.message==='voice_retry_confirmation_required'&&!options.auto&&window.confirm(t('voiceCost')))a=await create(true);else throw e}}
      if(a.status==='failed'&&!options.auto&&window.confirm(t('voiceCost')))a=await create(true);
      if(stamp!==epoch)return null;
      let preview=null;if(['preparing','running'].includes(a.status))preview=await livePreview(a,stamp,onState);
      if(['preparing','running'].includes(a.status))a=await new Promise((resolve,reject)=>{
        streamReject=reject;stream=new EventSource('/user/api/voice-audio/'+a.id+'/events');const events=stream;
        events.addEventListener('snapshot',event=>{const item=JSON.parse(event.data);if(stamp!==epoch){events.close();reject(new Error('voice_cancelled'));return}if(!['preparing','running'].includes(item.status)){events.close();if(stream===events){stream=null;streamReject=null}item.status==='ready'?resolve(item):reject(new Error(item.metadata.error_code||'voice_failed'))}});
        events.addEventListener('access_denied',()=>{events.close();reject(new Error('voice_access_denied'))});events.onerror=()=>{events.close();reject(new Error('voice_failed'))};
      });
      const played=preview?.position()||0;preview?.stop(false);if(previewAudio===preview)previewAudio=null;
      if(stamp!==epoch)return null;if(a.status!=='ready')throw new Error('voice_failed');assets.set(key,a);options.onReady?.(a);
      if(options.container){let element=options.container.querySelector('[data-audio-id="'+a.id+'"] audio');if(!element)element=player(a,options.container,onState);currentAudio=element;
        if(played>0){element.addEventListener('loadedmetadata',()=>{element.currentTime=Math.min(played,element.duration)},{once:true});element.preload='metadata'}
        element.onended=()=>onState('voiceEnded');element.onerror=()=>onState('voiceError');
        try{await element.play();onState('speaking')}catch(_){onState('audioAutoplay')}
      }
      return a;
    }catch(e){previewAudio?.stop();previewAudio=null;streamReject=null;if(stamp===epoch)onState(errorState(e));return null}
  }
  async function saveDialog(cid,available,title,onSaved=()=>{}){
    const eligible=available.filter(a=>a.status==='ready'&&!a.saved_at);
    if(!eligible.length){window.alert(t('audioMissing'));return}
    const dialog=node('dialog',undefined,'voice-save-dialog'),form=node('form');dialog.append(form);form.append(translated('h3','saveAudio'),translated('p','audioSaveNotice'));
    const titleInput=node('input');titleInput.type='text';titleInput.required=true;titleInput.maxLength=180;titleInput.value=(title||t('saveAudio')).slice(0,180);form.append(field('audioTitle',titleInput));
    const scope=node('select');for(const [value,key] of [['ai','aiAudio'],['dialogue','dialogueAudio']]){const o=translated('option',key);o.value=value;scope.append(o)}form.append(field('audioScope',scope));
    const selections=[];form.append(translated('h4','selectedAudio'));
    for(const a of eligible){const box=node('fieldset'),check=node('input');check.type='checkbox';check.checked=true;const l=field('playAnswer',check);l.querySelector('span').textContent=a.metadata.spoken_text?.slice(0,100)||a.title||t('playAnswer');box.append(l,node('p',a.duration_seconds.toFixed(1)+' s'));
      const begin=node('input'),end=node('input');for(const input of [begin,end]){input.type='number';input.min='0';input.max=a.duration_seconds;input.step='.001'}begin.value='0';end.value=String(a.duration_seconds);box.append(field('clipStart',begin),field('clipEnd',end));form.append(box);selections.push({a,check,begin,end});}
    const partial=node('input');partial.type='checkbox';form.append(field('audioPartial',partial));
    const status=node('p','','chat-status');status.role='status';form.append(status);const cancel=button('cancelAudio',()=>dialog.close()),confirm=translated('button','confirmAudio','btn primary');confirm.type='submit';form.append(cancel,confirm);
    let key=crypto.randomUUID(),signature=null,submitted=false;
    form.addEventListener('submit',async event=>{event.preventDefault();if(submitted)return;submitted=true;confirm.disabled=true;status.textContent=t('voicePreparing');
      try{const chosen=selections.filter(s=>s.check.checked).map(s=>({asset_id:s.a.id,start_seconds:Number(s.begin.value)===0&&Number(s.end.value)===s.a.duration_seconds?null:Number(s.begin.value),end_seconds:Number(s.begin.value)===0&&Number(s.end.value)===s.a.duration_seconds?null:Number(s.end.value)}));
        if(!chosen.length)throw new Error('voice_full_recording_unavailable');
        const body={scope:scope.value,title:titleInput.value.trim(),selections:chosen,retain_conversation:true,allow_partial:partial.checked};const next=JSON.stringify(body);if(signature&&signature!==next)key=crypto.randomUUID();signature=next;let job=await api('/user/api/conversations/'+cid+'/audio-saves',{method:'POST',body:JSON.stringify({idempotency_key:key,...body})});
        while(['preparing','running'].includes(job.status)){await new Promise(resolve=>setTimeout(resolve,500));job=await api('/user/api/conversations/'+cid+'/audio-saves/'+job.id)}
        if(job.status!=='completed')throw new Error(job.error_code||'voice_failed');onSaved(job);window.dispatchEvent(new Event('bee:memory-saved'));status.textContent=t('audioSaved');dialog.close();
      }catch(e){status.textContent=t(errorState(e));submitted=false;confirm.disabled=false}
    });
    dialog.addEventListener('keydown',event=>{if(['Escape','Tab'].includes(event.key))event.stopPropagation()});
    const previous=document.activeElement;dialog.addEventListener('close',()=>{dialog.remove();if(previous?.isConnected)previous.focus()},{once:true});(document.getElementById('newsDialog')?.contains(previous)?document.getElementById('newsDialog'):document.body).append(dialog);dialog.showModal();titleInput.focus();
  }
  async function attachMemory(parent,cid,onState=()=>{}){
    const data=await api('/user/api/conversations/'+cid+'/voice-audio');if(!parent.isConnected)return;
    for(const a of data.audio.filter(a=>a.saved_at&&a.status==='ready')){parent.append(node('h4',a.title),node('p',t(a.metadata.complete?'audioComplete':'audioIncomplete')+' · '+a.duration_seconds.toFixed(1)+' s'));player(a,parent,onState)}
    if(data.truncated)parent.append(node('p',t('partial')));
  }
  async function brief(ids,minutes,language,onState,options={}){
    const voices=caps.voices.filter(v=>v.languages.includes(language)),v=voices.find(v=>v.key===options.voiceKey)||voices[0];
    if(!caps.enabled||!v){onState('voiceNotConfigured');return null}
    stop();const stamp=epoch,key='brief:'+workspace+':'+v.key+':'+language+':'+minutes+':'+ids.join(',');
    try{
      let a=assets.get(key);
      if(a&&!a.saved_at&&new Date(a.expires_at).getTime()<=Date.now()){a=null;keys.delete(key)}
      if(!a){
        if(!window.confirm(t('voiceConsent')+'\n'+t('voiceCost')))return null;
        if(!keys.has(key))keys.set(key,crypto.randomUUID());
        a=await api('/user/api/assistants/'+workspace+'/brief-audio',{method:'POST',body:JSON.stringify({idempotency_key:keys.get(key),publication_ids:ids,voice_key:v.key,language,minutes,transfer_consent:true})});
        options.onCreated?.(a);onState('voicePreparing');
        if(['preparing','running'].includes(a.status))a=await new Promise((resolve,reject)=>{
          streamReject=reject;stream=new EventSource('/user/api/voice-audio/'+a.id+'/events');const events=stream;
          events.addEventListener('snapshot',event=>{const item=JSON.parse(event.data);if(stamp!==epoch){events.close();reject(new Error('voice_cancelled'));return}if(!['preparing','running'].includes(item.status)){events.close();stream=null;streamReject=null;item.status==='ready'?resolve(item):reject(new Error('voice_failed'))}});
          events.addEventListener('access_denied',()=>{events.close();reject(new Error('voice_failed'))});events.onerror=()=>{events.close();reject(new Error('voice_failed'))};
        });
      }
      if(stamp!==epoch)return null;
      assets.set(key,a);options.onReady?.(a);options.container?.replaceChildren();
      if(options.container){const audio=player(a,options.container,onState);audio.onended=()=>onState('voiceEnded');try{await audio.play();onState('speaking')}catch(_){onState('audioAutoplay')}}
      return a;
    }catch(e){streamReject=null;if(stamp===epoch)onState(errorState(e));return null}
  }
  function gallery(parent,aid){
    const box=node('details',undefined,'voice-library');box.append(translated('summary','audioSaved'));
    const form=node('form'),search=node('input');search.type='search';search.maxLength=120;form.append(field('audioTitle',search));
    const submit=button('search',()=>load());form.append(submit);form.addEventListener('submit',e=>{e.preventDefault();load()});
    const status=node('p','','chat-status');status.role='status';const list=node('div'),more=button('older',()=>load(true));more.hidden=true;
    box.append(form,status,list,more);parent.append(box);let cursor=null,busy=false,sequence=0;
    async function load(older=false){
      if(busy||!box.isConnected||window.BeeReader.workspace().id!==aid)return;busy=true;more.disabled=true;const stamp=++sequence;
      if(!older){list.querySelectorAll('audio').forEach(a=>a.pause());list.replaceChildren();cursor=null}
      try{
        const params=new URLSearchParams({q:search.value});if(older&&cursor)params.set('before',cursor);
        const data=await api('/user/api/assistants/'+aid+'/voice-audio?'+params);
        if(stamp!==sequence||!box.isConnected||window.BeeReader.workspace().id!==aid)return;
        for(const a of data.audio){
          const card=node('article');card.append(node('h4',a.title),node('p',t(a.metadata.complete?'audioComplete':'audioIncomplete')+' · '+a.duration_seconds.toFixed(1)+' s'));player(a,card,key=>status.textContent=t(key));
          const link=node('a',t('viewConversation'),'btn');link.href='/user?memory=1&assistant='+aid+'&conversation='+a.conversation_id;card.append(link);list.append(card);
        }
        cursor=data.older_before;more.hidden=!cursor;status.textContent=list.children.length?'':t('memoryEmpty');
      }catch(e){status.textContent=t(errorState(e))}finally{busy=false;more.disabled=false}
    }
    box.addEventListener('toggle',()=>{if(box.open)load();else box.querySelectorAll('audio').forEach(a=>a.pause())});
  }
  window.BeeNewsVoice={stop,clear,stopRecording,prepareInput,dictate,configure,answer,brief,gallery,player,saveDialog,attachMemory,api,
    get canDictate(){return Boolean(caps.enabled&&navigator.mediaDevices?.getUserMedia&&window.isSecureContext&&window.AudioContext)},
    canSpeak:language=>Boolean(caps.enabled&&caps.voices.some(v=>v.languages.includes(language))),
    capabilities:()=>caps,errorState,speak:(_text,_language,onState)=>{onState('voiceUnavailable');return false}};
  new MutationObserver(()=>{for(const n of document.querySelectorAll('[data-voice-key]'))n.textContent=t(n.dataset.voiceKey);for(const n of document.querySelectorAll('[data-voice-label]'))n.setAttribute('aria-label',t(n.dataset.voiceLabel))}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
  window.addEventListener('pagehide',clear);
  document.getElementById('assistantSelect')?.addEventListener('change',clear);
  const app=document.getElementById('app');if(app)new MutationObserver(()=>{if(app.classList.contains('hidden'))clear()}).observe(app,{attributes:true,attributeFilter:['class']});
})();
