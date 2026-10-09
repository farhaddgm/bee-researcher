
    /* Owner support inbox: keep the user's own tickets in «Tickets» and add a
       separate owner-only queue for every submitted ticket. The same PATCH
       route is used, so RBAC remains enforced server-side. */
    (function(){
      if(window.__beeCanonicalSupport)return;
      const copy={
        myTitle:{fa:'تیکت‌ها',en:'Tickets',tr:'Talepler',ar:'التذاكر',it:'Ticket',es:'Tickets',de:'Tickets',fr:'Tickets'},
        myHint:{fa:'تیکت‌هایی که خودتان ثبت کرده‌اید و آخرین وضعیت آن‌ها.',en:'Tickets you submitted and their latest status.',tr:'Gönderdiğiniz talepler ve son durumları.',ar:'التذاكر التي أرسلتموها وآخر حالاتها.',it:'I ticket inviati e il loro stato più recente.',es:'Tus tickets y su estado más reciente.',de:'Ihre Tickets und ihr aktueller Status.',fr:'Vos tickets et leur dernier statut.'},
        ownerTitle:{fa:'تیکت‌های ثبت‌شده',en:'Submitted tickets',tr:'Gönderilen talepler',ar:'التذاكر المرسلة',it:'Ticket inviati',es:'Tickets enviados',de:'Eingereichte Tickets',fr:'Tickets envoyés'},
        ownerHint:{fa:'همه تیکت‌های کاربران؛ پاسخ و وضعیت را از همین‌جا مدیریت کنین.',en:'Every user ticket; reply and update its status from here.',tr:'Tüm kullanıcı talepleri; yanıtı ve durumu buradan yönetin.',ar:'جميع تذاكر المستخدمين؛ أرسلوا الرد وحدّثوا الحالة من هنا.',it:'Tutti i ticket degli utenti; rispondi e aggiorna lo stato qui.',es:'Todos los tickets de usuarios; responde y actualiza el estado aquí.',de:'Alle Benutzertickets; antworten und Status hier aktualisieren.',fr:'Tous les tickets des utilisateurs ; répondez et mettez à jour le statut ici.'},
        empty:{fa:'هنوز تیکتی ثبت نشده است.',en:'No submitted tickets yet.',tr:'Henüz gönderilen talep yok.',ar:'لا توجد تذاكر مرسلة بعد.',it:'Non ci sono ancora ticket inviati.',es:'Aún no hay tickets enviados.',de:'Noch keine Tickets eingereicht.',fr:'Aucun ticket envoyé pour le moment.'},
        reply:{fa:'پاسخ مالک',en:'Owner reply',tr:'Sahip yanıtı',ar:'رد المالك',it:'Risposta del proprietario',es:'Respuesta del propietario',de:'Antwort des Eigentümers',fr:'Réponse du propriétaire'},
        save:{fa:'ذخیره پاسخ',en:'Save reply',tr:'Yanıtı kaydet',ar:'حفظ الرد',it:'Salva risposta',es:'Guardar respuesta',de:'Antwort speichern',fr:'Enregistrer la réponse'},
        open:{fa:'باز',en:'Open',tr:'Açık',ar:'مفتوح',it:'Aperto',es:'Abierto',de:'Offen',fr:'Ouvert'},
        in_progress:{fa:'در حال پیگیری',en:'In progress',tr:'İnceleniyor',ar:'قيد المتابعة',it:'In lavorazione',es:'En curso',de:'In Bearbeitung',fr:'En cours'},
        waiting_user:{fa:'منتظر پاسخ کاربر',en:'Waiting for user',tr:'Kullanıcı yanıtı bekleniyor',ar:'بانتظار رد المستخدم',it:'In attesa dell’utente',es:'Esperando al usuario',de:'Warten auf Benutzer',fr:'En attente de l’utilisateur'},
        resolved:{fa:'حل‌شده',en:'Resolved',tr:'Çözüldü',ar:'تم الحل',it:'Risolto',es:'Resuelto',de:'Gelöst',fr:'Résolu'},
        closed:{fa:'بسته‌شده',en:'Closed',tr:'Kapalı',ar:'مغلق',it:'Chiuso',es:'Cerrado',de:'Geschlossen',fr:'Fermé'},
        low:{fa:'کم',en:'Low',tr:'Düşük',ar:'منخفضة',it:'Bassa',es:'Baja',de:'Niedrig',fr:'Basse'},
        normal:{fa:'عادی',en:'Normal',tr:'Normal',ar:'عادية',it:'Normale',es:'Normal',de:'Normal',fr:'Normale'},
        high:{fa:'زیاد',en:'High',tr:'Yüksek',ar:'مرتفعة',it:'Alta',es:'Alta',de:'Hoch',fr:'Haute'},
        urgent:{fa:'فوری',en:'Urgent',tr:'Acil',ar:'عاجلة',it:'Urgente',es:'Urgente',de:'Dringend',fr:'Urgente'}
      };
      const t=key=>copy[key]?.[state.language]||copy[key]?.en||key;
      const isOwner=()=>Boolean(state.supportCanManage&& (state.currentUser?.is_owner||state.currentUser?.role==='owner'||state.supportCanManage));
      const ensureOwnerPanel=()=>{
        const root=document.getElementById('view-support'),grid=root?.querySelector('.support-layout');if(window.__supportV2Ready||!root||!grid)return;
        const setText=(node,value)=>{if(node&&node.textContent!==value)node.textContent=value};
        const ownTitle=root.querySelector('[data-support-title-list]');setText(ownTitle,t('myTitle'));
        let card=document.getElementById('support-submitted-card');
        if(!card){card=document.createElement('section');card.id='support-submitted-card';card.className='card section-card support-submitted-card';card.innerHTML='<div class="section-title"><h3 data-submitted-title></h3><span data-submitted-count></span></div><p class="support-submitted-hint" data-submitted-hint></p><div class="support-submitted-list" data-submitted-list></div>';grid.insertAdjacentElement('afterend',card)}
        const hidden=!isOwner();if(card.hidden!==hidden)card.hidden=hidden;setText(card.querySelector('[data-submitted-title]'),t('ownerTitle'));setText(card.querySelector('[data-submitted-hint]'),t('ownerHint'));renderOwnerTickets(card);
      };
      const renderOwnerTickets=card=>{
        if(!card||card.hidden)return;const tickets=state.supportAllTickets||[];const key=state.language+'|'+tickets.map(ticket=>[ticket.id,ticket.status,ticket.owner_reply||''].join(':')).join('|');if(card.dataset.renderKey===key)return;card.dataset.renderKey=key;
        const list=card.querySelector('[data-submitted-list]'),count=card.querySelector('[data-submitted-count]');if(count)count.textContent=state.language==='fa'?toFaDigits(tickets.length):String(tickets.length);if(!tickets.length){list.innerHTML='<div class="empty">'+esc(t('empty'))+'</div>';return}
        list.innerHTML=tickets.map(ticket=>{const statuses=['open','in_progress','waiting_user','resolved','closed'].map(status=>'<option value="'+status+'" '+(ticket.status===status?'selected':'')+'>'+esc(t(status))+'</option>').join('');return '<article class="support-submitted-ticket" data-submitted-ticket="'+esc(ticket.id)+'"><div class="support-submitted-ticket-head"><div><small class="support-ticket-number">'+esc(ticket.ticket_number||'SUP')+'</small><b>'+esc(ticket.subject)+'</b></div><span class="status">'+esc(t(ticket.status)||ticket.status)+'</span></div><div class="support-submitted-ticket-meta">'+esc(ticket.created_by||'—')+' · '+esc(fmtDate(ticket.created_at))+' · '+esc(t(ticket.priority)||ticket.priority)+'</div><p>'+esc(ticket.body)+'</p><div class="support-owner-controls"><textarea data-owner-reply="'+esc(ticket.id)+'" rows="2" placeholder="'+esc(t('reply'))+'"></textarea><div class="support-owner-actions"><select data-owner-status="'+esc(ticket.id)+'">'+statuses+'</select><button type="button" class="btn small primary" data-owner-save="'+esc(ticket.id)+'">'+esc(t('save'))+'</button></div></div></article>'}).join('');list.querySelectorAll('[data-owner-save]').forEach(button=>button.onclick=()=>saveOwnerTicket(button.dataset.ownerSave));
      };
      const saveOwnerTicket=async id=>{const root=document.getElementById('support-submitted-card');try{await req('/admin/api/support/tickets/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({status:root.querySelector('[data-owner-status="'+id+'"]').value,owner_reply:root.querySelector('[data-owner-reply="'+id+'"]').value})});toast(state.language==='en'?'Ticket updated.':'تیکت به‌روزرسانی شد.');if(window.loadSupportTickets)await window.loadSupportTickets()}catch(err){toast(friendlyError(err.message),true)}};
      const boot=()=>{const root=document.getElementById('view-support');if(!root)return;if(root.dataset.ownerSupportReady)return;root.dataset.ownerSupportReady='1';ensureOwnerPanel();new MutationObserver(()=>requestAnimationFrame(ensureOwnerPanel)).observe(root,{childList:true,subtree:true})};
      boot();new MutationObserver(boot).observe(document.querySelector('.content')||document.body,{childList:true,subtree:true});
    })();
