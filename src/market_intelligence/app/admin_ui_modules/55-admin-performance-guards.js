
    /* MI-210: keep read-heavy page refreshes responsive. The admin shell has
       several optional panels that ask for the same project payload during a
       single paint. The request layer already coalesces concurrent reads;
       this short cache also collapses sequential duplicates while preserving
       fresh data after every mutation. */
    (function(){
      const raw=window.req,cacheTtl=1200;
      if(typeof raw==='function'&&!raw.__adminReadCache){
        const cache=new Map();let generation=0,lastActor='';
        const cached=async function(path,opts={}){
          const actor=String(state.currentUser?.id||'')+':'+String(state.assistantId||'');
          if(actor!==lastActor){lastActor=actor;cache.clear();generation++;}
          for(const [oldKey,item]of cache)if(item.expires<=Date.now())cache.delete(oldKey);
          const method=String(opts?.method||'GET').toUpperCase(),key=actor+':'+String(path);
          const cacheable=method==='GET'&&!/\/login|\/logout|\/csp-report|\/admin\/api\/me(?:\?|$)/i.test(String(path));
          // Explicit refreshes (coalesceGet:false) must bypass both layers of
          // request deduplication. Leaving the short read cache in front of
          // the request layer caused the Operations refresh button to return
          // stale incidents even though loadIncidents(true) opted out of GET
          // coalescing below.
          if(method==='GET'&&opts?.coalesceGet===false){cache.delete(key);generation++;return raw(path,opts)}
          if(!cacheable){cache.clear();generation++;try{return await raw(path,opts)}finally{cache.clear();generation++}}
          const hit=cache.get(key);if(hit&&hit.expires>Date.now())return hit.value;
          const version=generation,value=await raw(path,opts);
          if(version===generation){if(cache.size>=64)cache.delete(cache.keys().next().value);cache.set(key,{value,expires:Date.now()+cacheTtl});}return value
        };
        cached.__adminReadCache=true;window.req=cached;try{req=cached}catch(_){ }
      }
      // Full-refresh deduplication belongs exclusively to BeeAdminLifecycle.
      ['refreshBtn','systemRefreshBtn'].forEach(id=>{const button=document.getElementById(id);if(button)button.onclick=window.__researchBeeRefreshBackoffice||(()=>window.loadAll())});
      window.__researchBeePerformanceGuards={readCache:true,singleFlight:true,ttl:cacheTtl};
    })();
