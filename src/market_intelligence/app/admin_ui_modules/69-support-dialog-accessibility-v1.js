
    // Keep keyboard focus inside the ticket conversation and return it to the
    // selected ticket when the modal closes. The support controller is
    // intentionally isolated from the older shared modal implementation.
    (()=>{
      let opener=null,openerTicketId='';
      const dialog=()=>document.getElementById('support-ticket-v4-dialog');
      const focusable=scope=>[...scope.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(node=>!node.hidden&&node.getAttribute('aria-hidden')!=='true'&&node.getClientRects().length);
      let restorePending=false;
      const restoreOpener=()=>{const scope=dialog(),supportRoot=document.getElementById('view-support');if(!restorePending||!scope||!scope.hidden||supportRoot?.getAttribute('aria-busy')==='true')return;let target=openerTicketId?[...document.querySelectorAll('[data-support-v4-ticket]')].find(node=>node.dataset.supportV4Ticket===openerTicketId)||null:null;if(!target&&opener?.isConnected&&opener!==document.body&&opener!==document.documentElement)target=opener;if(target){opener=null;openerTicketId='';restorePending=false;target.focus()}};
      const bind=scope=>{
        if(!scope||scope.dataset.keyboardA11yBound==='1')return;
        scope.dataset.keyboardA11yBound='1';
        const modal=scope.querySelector('[role="dialog"]');
        if(modal){const title=modal.querySelector('[data-support-v4-dialog-title]');if(title){title.id='support-v4-dialog-title';modal.setAttribute('aria-labelledby',title.id)}const close=modal.querySelector('[data-support-v4-dialog-close]');if(close){const labels={fa:'بستن پنجره',en:'Close dialog',tr:'Pencereyi kapat',ar:'إغلاق النافذة',it:'Chiudi finestra',es:'Cerrar diálogo',de:'Dialog schließen',fr:'Fermer la boîte de dialogue'};close.setAttribute('aria-label',labels[window.state?.language]||labels.en)}}
        scope.addEventListener('keydown',event=>{if(event.key!=='Tab'||scope.hidden)return;const items=focusable(scope);if(!items.length){event.preventDefault();return}const first=items[0],last=items[items.length-1];if(event.shiftKey&&(document.activeElement===first||!scope.contains(document.activeElement))){event.preventDefault();last.focus()}else if(!event.shiftKey&&(document.activeElement===last||!scope.contains(document.activeElement))){event.preventDefault();first.focus()}});
      };
      const install=()=>{const api=window.__supportTicketV4;if(api&&typeof api.openDialog==='function'&&!api.openDialog.__keyboardA11y){const original=api.openDialog;const wrapped=function(){const active=document.activeElement;if(!openerTicketId&&active&&active!==document.body&&active!==document.documentElement)opener=active;const result=original.apply(this,arguments);bind(dialog());return result};wrapped.__keyboardA11y=true;api.openDialog=wrapped}bind(dialog())};
      document.addEventListener('click',event=>{const ticket=event.target.closest?.('[data-support-v4-ticket]');if(ticket){opener=ticket;openerTicketId=ticket.dataset.supportV4Ticket||'';restorePending=false;requestAnimationFrame(()=>{install();bind(dialog())})}},true);
      document.addEventListener('support-ticket-dialog-closed',event=>{restorePending=true;if(event.detail?.refreshing)return;requestAnimationFrame(restoreOpener)});
      install();const supportRoot=document.getElementById('view-support');if(supportRoot)new MutationObserver(()=>{install();restoreOpener()}).observe(supportRoot,{childList:true,subtree:true,attributes:true,attributeFilter:['aria-busy']});
    })();
