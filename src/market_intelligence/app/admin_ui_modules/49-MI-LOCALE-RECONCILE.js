
    // MI-LOCALE-RECONCILE: renderers can replace text inside an existing
    // panel without adding a new element, so a childList-only observer cannot
    // see the change. Reconcile once after each supported render/load/view
    // operation and after late-created panels. This is deliberately
    // event-driven (no polling) and keeps user-entered article/business/source
    // values out of the copy pass.
    (function(){
      const selectors=['#login','#sidebar','.topbar','.content','#modalRoot'];
      const ignored='[data-dynamic-copy],[data-latin="true"],.article-body,.news-title-cell,.assistant-card h3,.assistant-card p,.assistant-card .assistant-meta b,#sourceRows td:first-child b,#topicRows td:first-child b,#feedbackActorRows .feedback-user b,#channelGrid b[data-latin="true"],#channelGrid code.channel-id,[data-user-content="true"]';
      const pluralLabels={
        users:{fa:'کاربر',en:'user',tr:'kullanıcı',ar:'مستخدم',it:'utenti',es:'usuarios',de:'Benutzer',fr:'utilisateurs'},
        media:{fa:'رسانه',en:'media',tr:'medya',ar:'الوسائط',it:'media',es:'medios',de:'Medien',fr:'médias'},
        topics:{fa:'موضوع',en:'topic',tr:'konu',ar:'موضوع',it:'argomento',es:'tema',de:'Thema',fr:'sujet'},
        items:{fa:'مورد',en:'item',tr:'öğe',ar:'عنصر',it:'elemento',es:'elemento',de:'Element',fr:'élément'}
      };
      let aliasCache={language:'',entries:[]};
      const preserve=(raw,next)=>{const left=raw.match(/^\s*/)?.[0]||'',right=raw.match(/\s*$/)?.[0]||'';return left+next+right};
      const localizedCount=(count,kind)=>{
        const number=localeNumber(toLatinDigits(count)),language=state.language,labels=pluralLabels[kind]||pluralLabels.items;
        if(language==='en'&&kind==='users')return `${number} ${Number(toLatinDigits(count))===1?'user':'users'}`;
        return `${number} ${labels[language]||labels.en}`;
      };
      const dynamicCopy=(value)=>{
        const text=String(value??''),trimmed=text.trim();if(!trimmed)return text;
        let match=trimmed.match(/^([0-9۰-۹]+)\s*(کاربر|users?|utilisateurs|Benutzer|usuarios|utenti|kullanıcı|مستخدمون|مستخدم)$/i);
        if(match)return localizedCount(match[1],'users');
        match=trimmed.match(/^([0-9۰-۹]+)\s*(موضوع|topics?|sujets?|temas|Themen|argomenti|konu|موضوعًا)$/i);
        if(match)return localizedCount(match[1],'topics');
        match=trimmed.match(/^([0-9۰-۹]+)\s*(رسانه|media|medios|médias|Medien|medya|مصدر)$/i);
        if(match)return localizedCount(match[1],'media');
        match=trimmed.match(/^([0-9۰-۹]+)\s*(مورد|items?|öğe|عنصر|elementi|elementos|Elemente|éléments)$/i);
        if(match)return localizedCount(match[1],'items');
        match=trimmed.match(/^([0-9۰-۹]+)\s+publishing hours selected across\s+([0-9۰-۹]+)\s+days$/i);
        if(match){const c=localeNumber(toLatinDigits(match[1])),d=localeNumber(toLatinDigits(match[2]));const words={fa:`${c} ساعت انتشار در ${d} روز انتخاب شده است`,tr:`${c} yayın saati ${d} güne dağıtıldı`,ar:`تم اختيار ${c} ساعة نشر عبر ${d} أيام`,it:`${c} ore di pubblicazione selezionate su ${d} giorni`,es:`${c} horas de publicación seleccionadas en ${d} días`,de:`${c} Veröffentlichungsstunden an ${d} Tagen ausgewählt`,fr:`${c} heures de publication sélectionnées sur ${d} jours`};return words[state.language]||`${c} publishing hours selected across ${d} days`}
        const current=String(state.language||'en');
        if(aliasCache.language!==current){
          const bySource=new Map();
          for(const row of Object.values(uxWritingCatalog||{})){
            const target=String(row?.[current]??'').trim();if(!target||target==='—')continue;
            for(const candidate of Object.values(row||{})){const source=String(candidate??'').trim();if(source.length>1&&source!==target&&!bySource.has(source))bySource.set(source,target)}
          }
          aliasCache={language:current,entries:[...bySource.entries()].sort((a,b)=>b[0].length-a[0].length)};
        }
        let result=trimmed;
        // Use placeholders so replacing an alias never feeds the translated
        // value back into another alias during the same pass.
        const replacements=[];aliasCache.entries.forEach(([source,target],index)=>{
          if(!result.includes(source)||source===target)return;
          const token=`\uE000${index}\uE001`;
          // Short labels such as "in", "or", "ID" and their translated
          // equivalents must never be replaced inside a longer word. This
          // was the cause of corrupted navigation labels like
          // "Assistenteeeee" after switching locales repeatedly. Phrases
          // containing whitespace/punctuation are safe to replace inline;
          // single-word aliases use Unicode-aware boundaries.
          if(/^[\p{L}\p{N}_]+$/u.test(source)){
            const escaped=source.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
            const boundary=new RegExp(`(^|[^\\p{L}\\p{N}_])${escaped}(?=$|[^\\p{L}\\p{N}_])`,'gu');
            if(!boundary.test(result))return;
            result=result.replace(boundary,(match,prefix)=>prefix+token);
          }else result=result.split(source).join(token);
          replacements.push([token,target]);
        });
        replacements.forEach(([token,target])=>{result=result.split(token).join(target)});
        return result;
      };
      const settle=()=>{
        if(window.__researchBeeLocaleApplying)return;
        try{
          window.__researchBeeLocalizeAll?.();
          window.__researchBeeRunLocaleScrub?.();
          translateStaticCopy?.();
          selectors.forEach(selector=>document.querySelectorAll(selector).forEach(root=>{
            const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
            while(node=walker.nextNode()){
              const parent=node.parentElement;if(!parent||['SCRIPT','STYLE','INPUT','TEXTAREA','PRE','CODE','OPTION'].includes(parent.tagName)||parent.closest(ignored)||parent.closest(reportProseSelector))continue;
              // Only reviewed catalog aliases and known composite counters are
              // rewritten. Arbitrary user-entered values remain unchanged.
              const raw=node.nodeValue||'',trimmed=raw.trim();if(!trimmed)continue;
              const next=dynamicCopy(trimmed);if(next!==trimmed)node.nodeValue=preserve(raw,next);
            }
          }));
        }catch(_){ }
      };
      let settleQueued=false;
      const schedule=()=>{
        if(settleQueued)return;
        settleQueued=true;
        queueMicrotask(()=>{settleQueued=false;settle()});
      };
      window.BeeAdminLifecycle.register('locale-reconcile', ['setView','setLanguage','loadAll','renderDashboard','renderQualityReport','renderAssistants','renderSources','renderTopics','renderPublications','renderTelegram','renderOperations','renderScheduleGrid','renderChannels'], {settled:schedule});
      document.addEventListener('click',event=>{if(event.target?.closest?.('.nav-btn,[data-language-select],#refreshBtn,#systemRefreshBtn'))schedule()},{capture:true});
      settle();
    })();
