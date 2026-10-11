/* Device speech, invoked only by an explicit microphone/play/send action. */
(() => {
  'use strict';
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const synth=window.speechSynthesis;
  let recognition=null,utterance=null,epoch=0;
  const voiceFor=language=>synth?.getVoices().find(v=>v.lang.toLowerCase().split(/[-_]/)[0]===language);
  function stop(){
    epoch++;
    if(recognition){const old=recognition;recognition=null;old.abort()}
    if(utterance){utterance=null;synth?.cancel()}
  }
  function dictate(language,onText,onState){
    stop();
    if(!Recognition||!window.isSecureContext){onState('voiceUnavailable');return}
    const current=epoch,session=new Recognition();recognition=session;
    session.lang={fa:'fa-IR',en:'en-US',tr:'tr-TR',ar:'ar-SA',es:'es-ES',it:'it-IT',de:'de-DE',fr:'fr-FR'}[language]||language;
    session.continuous=false;session.interimResults=false;session.maxAlternatives=1;
    session.onresult=event=>{
      if(current!==epoch)return;
      const text=Array.from(event.results).filter(r=>r.isFinal).map(r=>r[0].transcript).join(' ').trim();
      if(text)onText(text);onState('voiceReview');
    };
    session.onerror=()=>{if(current===epoch)onState('voiceError')};
    session.onend=()=>{if(current===epoch){recognition=null;onState('voiceEnded')}};
    try{session.start();onState('listening')}catch(_){recognition=null;onState('voiceError')}
  }
  function speak(text,language,onState){
    stop();
    const voice=voiceFor(language);
    if(!voice||!window.SpeechSynthesisUtterance){onState('voiceUnavailable');return false}
    // Short chunks avoid device engines silently dropping long answers.
    const chunks=text.match(/[\s\S]{1,220}(?:\s|$)|[\s\S]{1,220}/g)||[],current=epoch;
    function next(){
      if(current!==epoch)return;
      if(!chunks.length){utterance=null;onState('voiceEnded');return}
      const u=new SpeechSynthesisUtterance(chunks.shift());u.voice=voice;u.lang=voice.lang;utterance=u;
      u.onend=next;u.onerror=()=>{if(current===epoch){utterance=null;onState('voiceError')}};
      synth.speak(u);
    }
    onState('speaking');next();return true;
  }
  window.BeeNewsVoice={stop,dictate,speak,canDictate:Boolean(Recognition&&window.isSecureContext),canSpeak:language=>Boolean(voiceFor(language))};
  window.addEventListener('pagehide',stop);
})();
