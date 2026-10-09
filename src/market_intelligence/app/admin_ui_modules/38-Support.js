
    /* Support refresh: a focused help-desk workspace inspired by modern
       ticketing tools (clear compose flow, visible queue state, and compact
       ticket cards). It decorates the existing API-backed view without
       changing the ticket contract or owner permissions. */
    (function(){
      if(window.__beeCanonicalSupport)return;
      const text={
        all:{fa:'همه تیکت‌ها',en:'All tickets',tr:'Tüm talepler',ar:'كل التذاكر',it:'Tutti i ticket',es:'Todos los tickets',de:'Alle Tickets',fr:'Tous les tickets'},
        open:{fa:'باز',en:'Open',tr:'Açık',ar:'مفتوح',it:'Aperto',es:'Abierto',de:'Offen',fr:'Ouvert'},
        progress:{fa:'در حال پیگیری',en:'In progress',tr:'İnceleniyor',ar:'قيد المتابعة',it:'In lavorazione',es:'En curso',de:'In Bearbeitung',fr:'En cours'},
        waiting:{fa:'منتظر پاسخ',en:'Waiting for reply',tr:'Yanıt bekleniyor',ar:'بانتظار الرد',it:'In attesa di risposta',es:'Esperando respuesta',de:'Warten auf Antwort',fr:'En attente de réponse'},
        resolved:{fa:'حل‌شده',en:'Resolved',tr:'Çözüldü',ar:'تم الحل',it:'Risolto',es:'Resuelto',de:'Gelöst',fr:'Résolu'},
        tickets:{fa:'تیکت',en:'ticket',tr:'talep',ar:'تذكرة',it:'ticket',es:'ticket',de:'Ticket',fr:'ticket'},
        composeHint:{fa:'موضوع را انتخاب کنین، جزئیات را بنویسین و اولویت رسیدگی را مشخص کنین.',en:'Choose a topic, add the details, and set a priority so we can route your request quickly.',tr:'Bir konu seçin, ayrıntıları yazın ve talebinizi hızlıca yönlendirmek için öncelik belirleyin.',ar:'اختروا الموضوع وأضيفوا التفاصيل وحددوا الأولوية لتوجيه طلبكم بسرعة.',it:'Scegli l’argomento, aggiungi i dettagli e imposta la priorità per indirizzare rapidamente la richiesta.',es:'Elige un tema, añade los detalles y define la prioridad para dirigir rápido tu solicitud.',de:'Wählen Sie ein Thema, ergänzen Sie die Details und setzen Sie eine Priorität für die schnelle Zuordnung.',fr:'Choisissez un sujet, ajoutez les détails et définissez une priorité pour orienter rapidement votre demande.'},
        queueHint:{fa:'پاسخ مالک و تغییر وضعیت همین‌جا نمایش داده می‌شود.',en:'Owner replies and status changes appear here.',tr:'Sahibin yanıtı ve durum değişiklikleri burada görünür.',ar:'تظهر ردود المالك وتغييرات الحالة هنا.',it:'Le risposte del proprietario e gli aggiornamenti di stato compaiono qui.',es:'Aquí aparecen las respuestas del propietario y los cambios de estado.',de:'Antworten des Eigentümers und Statusänderungen erscheinen hier.',fr:'Les réponses du propriétaire et les changements de statut apparaissent ici.'},
        responseHint:{fa:'پاسخ‌ها و وضعیت تیکت را از همین صفحه دنبال کنین.',en:'Track replies and ticket status from this page.',tr:'Yanıtları ve talep durumunu bu sayfadan takip edin.',ar:'تابعوا الردود وحالة التذكرة من هذه الصفحة.',it:'Segui risposte e stato del ticket da questa pagina.',es:'Consulta aquí las respuestas y el estado del ticket.',de:'Verfolgen Sie Antworten und Ticketstatus auf dieser Seite.',fr:'Suivez ici les réponses et le statut du ticket.'},
        priority:{fa:'اولویت رسیدگی',en:'Response priority',tr:'Yanıt önceliği',ar:'أولوية الرد',it:'Priorità di risposta',es:'Prioridad de respuesta',de:'Antwortpriorität',fr:'Priorité de réponse'},
        low:{fa:'کم',en:'Low',tr:'Düşük',ar:'منخفضة',it:'Bassa',es:'Baja',de:'Niedrig',fr:'Basse'},
        normal:{fa:'عادی',en:'Normal',tr:'Normal',ar:'عادية',it:'Normale',es:'Normal',de:'Normal',fr:'Normale'},
        high:{fa:'زیاد',en:'High',tr:'Yüksek',ar:'مرتفعة',it:'Alta',es:'Alta',de:'Hoch',fr:'Haute'},
        urgent:{fa:'فوری',en:'Urgent',tr:'Acil',ar:'عاجلة',it:'Urgente',es:'Urgente',de:'Dringend',fr:'Urgente'}
      };
      const t=key=>text[key]?.[state.language]||text[key]?.en||key;
      const ensure=()=>{
        const root=document.getElementById('view-support');if(window.__supportV2Ready||!root)return;
        root.classList.add('support-redesign');
        const grid=root.querySelector('.two-col');if(!grid)return;
        grid.classList.add('support-layout');
        const compose=grid.children[0],inbox=grid.children[1];
        if(compose){compose.classList.add('support-compose-card');const title=compose.querySelector('.section-title');if(title&&!compose.querySelector('.support-compose-hint')){const hint=document.createElement('p');hint.className='support-compose-hint';hint.textContent=t('composeHint');title.insertAdjacentElement('afterend',hint)}ensurePriority(compose);ensureFormMeta(compose)}
        if(inbox){inbox.classList.add('support-inbox-card');const title=inbox.querySelector('.section-title');if(title&&!inbox.querySelector('.support-queue-hint')){const hint=document.createElement('p');hint.className='support-queue-hint';hint.textContent=t('queueHint');title.insertAdjacentElement('afterend',hint)}ensureFilters(inbox);}
        enhanceList(root);
      };
      const ensureFormMeta=compose=>{
        const form=compose.querySelector('[data-support-form]');if(!form)return;
        const body=form.querySelector('[data-support-body]');if(body&&!body.dataset.counterReady){body.dataset.counterReady='1';const counter=document.createElement('span');counter.className='support-char-count';counter.setAttribute('aria-live','polite');body.insertAdjacentElement('afterend',counter);const update=()=>{counter.textContent=`${body.value.length.toLocaleString()} / 10,000`;};body.addEventListener('input',update);update()}
        const submit=form.querySelector('[data-support-submit]');if(submit&&!form.querySelector('.support-submit-note')){const row=document.createElement('div');row.className='support-submit-row';submit.replaceWith(row);row.append(submit);const note=document.createElement('span');note.className='support-submit-note';note.textContent=t('responseHint');row.append(note)}
      };
      const ensurePriority=compose=>{
        const select=compose.querySelector('[data-support-priority]');if(!select)return;
        const field=select.closest('.field');if(!field)return;
        field.classList.add('support-priority-field');const label=field.querySelector('label'),priorityLabel=t('priority');if(label&&label.textContent!==priorityLabel)label.textContent=priorityLabel;
        let group=field.querySelector('.support-priority-options');if(!group){group=document.createElement('div');group.className='support-priority-options';select.insertAdjacentElement('afterend',group)}
        const values=['low','normal','high','urgent'];const markup=values.map(value=>`<button type="button" class="support-priority-option" data-priority-value="${value}" aria-pressed="${select.value===value?'true':'false'}">${t(value)}</button>`).join('');if(group.innerHTML!==markup)group.innerHTML=markup;if(!select.hidden)select.hidden=true;group.querySelectorAll('button').forEach(button=>button.onclick=()=>{select.value=button.dataset.priorityValue;select.dispatchEvent(new Event('change',{bubbles:true}));group.querySelectorAll('button').forEach(item=>item.setAttribute('aria-pressed',String(item===button)))})
      };
      const ensureFilters=inbox=>{
        const title=inbox.querySelector('.section-title');if(!title)return;
        let filters=inbox.querySelector('.support-filters');if(!filters){filters=document.createElement('div');filters.className='support-filters';title.insertAdjacentElement('afterend',filters)}
        const active=filters.dataset.active||'all';filters.dataset.active=active;const markup=['all','open','progress','resolved'].map(key=>`<button type="button" class="support-filter ${active===key?'active':''}" data-support-filter="${key}">${t(key)}</button>`).join('');if(filters.innerHTML!==markup)filters.innerHTML=markup;filters.querySelectorAll('button').forEach(button=>button.onclick=()=>{filters.dataset.active=button.dataset.supportFilter;filters.querySelectorAll('button').forEach(item=>item.classList.toggle('active',item===button));enhanceList(document.getElementById('view-support'))});
      };
      const enhanceList=root=>{
        const list=root.querySelector('[data-support-list]');if(!list)return;const tickets=state.supportTickets||[];const items=[...list.querySelectorAll('.detail-item')];items.forEach((item,index)=>{item.classList.add('support-ticket-item');const ticket=tickets[index];if(ticket){item.dataset.ticketStatus=ticket.status||'open';item.dataset.ticketPriority=ticket.priority||'normal';item.dataset.ticketNumber=ticket.ticket_number||'';}});
        const filters=root.querySelector('.support-filters'),active=filters?.dataset.active||'all';items.forEach(item=>{const status=item.dataset.ticketStatus||'open';const matches=active==='all'||(active==='progress'&&status==='in_progress')||(active==='resolved'&&['resolved','closed'].includes(status))||(active==='open'&&['open','waiting_user'].includes(status));const hidden=!matches;if(item.hidden!==hidden)item.hidden=hidden});
        const count=root.querySelector('[data-support-count]');if(count){const visible=items.filter(item=>!item.hidden).length;const value=state.language==='fa'?`${toFaDigits(visible)} ${t('tickets')}`:`${visible} ${t('tickets')}`;if(count.textContent!==value)count.textContent=value}
      };
      const refresh=()=>{ensure();const root=document.getElementById('view-support');if(root){const write=(node,value)=>{if(node&&node.textContent!==value)node.textContent=value};write(root.querySelector('.support-compose-hint'),t('composeHint'));write(root.querySelector('.support-queue-hint'),t('queueHint'));write(root.querySelector('.support-submit-note'),t('responseHint'));ensurePriority(root.querySelector('.support-compose-card')||root);ensureFilters(root.querySelector('.support-inbox-card')||root);enhanceList(root)}};
      const boot=()=>{const root=document.getElementById('view-support');if(window.__supportV2Ready||!root)return;refresh();if(root.dataset.supportObserver)return;root.dataset.supportObserver='1';const list=root.querySelector('[data-support-list]');if(!list)return;new MutationObserver(()=>{if(!root.dataset.supportRefreshing){root.dataset.supportRefreshing='1';requestAnimationFrame(()=>{root.dataset.supportRefreshing='';enhanceList(root)})}}).observe(list,{childList:true})};
      /* The base support view is constructed immediately before this layer.
         Observing the whole content tree here made this enhancer observe its
         own DOM writes, then call refresh again in the next microtask.  That
         self-sustaining loop blocked parsing before the login form became
         usable.  The scoped observer above is enough for ticket rows that
         are rendered later, provided refresh remains idempotent. */
      boot();
    })();
