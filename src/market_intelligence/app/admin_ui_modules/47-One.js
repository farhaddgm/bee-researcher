
    // One final, synchronous digit pass protects legacy renderers without
    // introducing another background watcher.  It runs only after a render or
    // data load, so the browser never paints an intermediate digit system.
    (function(){
      const numberIds=['kpiSources','kpiAnalyses','kpiPubs','kpiFeedback','qualityTotal','qualityRelevant','qualityIrrelevant','feedbackUniqueActors','sourceCount','topicCount','publicationCount','bulkNewsCount','maxItemsPerRun','freshnessWindowDays','limitMaxSources','limitMaxTopics','limitMaxFreshness','limitMaxItems','limitMaxBusinesses','limitMaxProjects'];
      const apply=()=>{
        numberIds.forEach(id=>{
          const node=$(id);if(!node)return;
          const source=node.value!==undefined?String(node.value):String(node.textContent||'');
          const match=source.match(/[0-9۰-۹]+(?:[.,][0-9۰-۹]+)?/);if(!match)return;
          const value=displayDigits(toLatinDigits(match[0]));
          if(node.value!==undefined){const next=source.slice(0,match.index)+value+source.slice(match.index+match[0].length);if(node.value!==next)node.value=next}
          else{const next=source.slice(0,match.index)+value+source.slice(match.index+match[0].length);if(node.textContent!==next)node.textContent=next}
        });
        document.querySelectorAll('[data-number]').forEach(node=>{const raw=node.dataset.number??node.textContent??'';const value=displayDigits(toLatinDigits(raw));if(node.textContent!==value)node.textContent=value});
      };
      const wrap=(name,assign)=>{const original=window[name];if(typeof original!=='function'||original.__stableDigits)return;const wrapped=function(){const result=original.apply(this,arguments);if(result&&typeof result.then==='function')return result.finally(apply);apply();return result};wrapped.__stableDigits=true;window[name]=wrapped;if(assign)assign(wrapped)};
      wrap('__researchBeePaintOverview');
      wrap('renderDashboard',value=>{renderDashboard=value});
      wrap('refreshOverviewKpis',value=>{refreshOverviewKpis=value});
      const originalLoadAll=loadAll;if(typeof originalLoadAll==='function'&&!originalLoadAll.__stableDigits){const wrappedLoadAll=async function(){const result=await originalLoadAll.apply(this,arguments);apply();return result};wrappedLoadAll.__stableDigits=true;loadAll=wrappedLoadAll;window.loadAll=wrappedLoadAll}
      window.__researchBeeNormalizeDigits=apply;
      apply();
    })();
