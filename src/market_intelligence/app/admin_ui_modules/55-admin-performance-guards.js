
    /* MI-210: keep read-heavy page refreshes responsive. The admin shell has
       several optional panels that ask for the same project payload during a
       single paint. The request layer already coalesces concurrent reads;
       this short cache also collapses sequential duplicates while preserving
       fresh data after every mutation. */
    (function(){
      const raw=window.req,cacheTtl=1200;
      if(typeof raw==='function'&&!raw.__adminReadCache){
        const cache=new Map();
        const cached=async function(path,opts={}){
          const method=String(opts?.method||'GET').toUpperCase(),key=String(state.currentUser?.id||'')+':'+String(state.assistantId||'')+':'+String(path);
          const cacheable=method==='GET'&&!/\/login|\/logout|\/csp-report/i.test(key);
          // Explicit refreshes (coalesceGet:false) must bypass both layers of
          // request deduplication. Leaving the short read cache in front of
          // the request layer caused the Operations refresh button to return
          // stale incidents even though loadIncidents(true) opted out of GET
          // coalescing below.
          if(method==='GET'&&opts?.coalesceGet===false){cache.delete(key);return raw(path,opts)}
          if(!cacheable){cache.clear();return raw(path,opts)}
          const hit=cache.get(key);if(hit&&hit.expires>Date.now())return hit.value;
          const value=await raw(path,opts);cache.set(key,{value,expires:Date.now()+cacheTtl});return value
        };
        cached.__adminReadCache=true;window.req=cached;try{req=cached}catch(_){ }
      }
      const current=window.loadAll;
      if(typeof current==='function'&&!current.__adminPerformanceSingleFlight){
        let flight=null;
        const guarded=function(){if(flight)return flight;flight=Promise.resolve().then(()=>current.apply(this,arguments)).finally(()=>{flight=null});return flight};
        guarded.__adminPerformanceSingleFlight=true;window.loadAll=guarded;try{loadAll=guarded}catch(_){ }
        ['refreshBtn','systemRefreshBtn'].forEach(id=>{const button=document.getElementById(id);if(button)button.onclick=window.__researchBeeRefreshBackoffice||guarded})
      }
      window.__researchBeePerformanceGuards={readCache:true,singleFlight:true,ttl:cacheTtl};
    })();
