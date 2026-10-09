// CSP-safe declarative action binding. No eval, inline handlers or style attributes.
(function () {
  const eventNames = ['click','change','input','submit','keydown','keyup','focus','blur'];
  const allowed = new Set(['renderSources','renderTopics','openPublication','setView','selectAssistant',
    'checkAssistantReadiness','openAssistantModal','openCloneAssistantModal','activateAssistant',
    'toggleSource','openSourceModal','toggleTopic','openTopicModal','editUser','revokeSession',
    'closeModal','publishFromReview','manageUserAccess','deleteUser','activateBusiness',
    'openBusinessEditor','deleteBusiness','deleteSourceFromUi','deleteTopicFromUi',
    'restoreAssistantFromUi','permanentDeleteAssistantFromUi','runIncidentHealth','closeIncident']);
  function splitArgs(text) {
    const result=[]; let quote='',escaped=false,start=0,depth=0;
    for(let i=0;i<text.length;i++) {
      const ch=text[i]; if(escaped){escaped=false;continue}
      if(ch==='\\'){escaped=true;continue}
      if(quote){if(ch===quote)quote='';continue}
      if(ch==='"'||ch==="'"){quote=ch;continue}
      if(ch==='('||ch==='['||ch==='{')depth++;
      if(ch===')'||ch===']'||ch==='}')depth--;
      if(ch===','&&!depth){result.push(text.slice(start,i).trim());start=i+1}
    }
    const last=text.slice(start).trim(); if(last)result.push(last); return result;
  }
  function parseArg(value) {
    if(value==='true')return true; if(value==='false')return false; if(value==='null')return null;
    if(/^-?\d+(?:\.\d+)?$/.test(value))return Number(value);
    if(value[0]==='{'||value[0]==='[')return JSON.parse(value);
    if(value[0]!==value[value.length-1]||!['"',"'"].includes(value[0]))throw new Error('invalid UI argument');
    let out='',escaped=false;
    for(const ch of value.slice(1,-1)) {
      if(!escaped){if(ch==='\\'){escaped=true;continue}out+=ch;continue}
      out+=({n:'\n',t:'\t',r:'\r'})[ch]??ch; escaped=false;
    }
    if(escaped)out+='\\'; return out;
  }
  function bind(node) {
    if(!(node instanceof Element))return;
    for(const eventName of eventNames) {
      const attribute='data-ui-'+eventName;
      if(!node.hasAttribute(attribute))continue;
      const match=(node.getAttribute(attribute)||'').trim().match(/^([A-Za-z_$][\w$]*)\(([\s\S]*)\)\s*;?$/);
      if(!match||!allowed.has(match[1]))throw new Error('unknown UI action');
      const args=splitArgs(match[2]).map(parseArg);
      node.removeAttribute(attribute);
      node.addEventListener(eventName,event=>{
        const fn=window[match[1]];
        if(typeof fn==='function'&&fn(...args,event)===false&&eventName==='submit')event.preventDefault();
      });
    }
  }
  const selector=eventNames.map(name=>'[data-ui-'+name+']').join(',');
  function scan(root){bind(root);root.querySelectorAll?.(selector).forEach(bind)}
  scan(document.body);
  new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{
    if(node.nodeType===Node.ELEMENT_NODE)scan(node);
  }))).observe(document.body,{subtree:true,childList:true});
})();
