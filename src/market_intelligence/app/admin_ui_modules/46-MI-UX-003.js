
    // MI-UX-003: make the Google Sheet catalog authoritative for every
    // server-rendered label, including nav items that contain an icon child.
    // Dynamic views still call translateStaticCopy explicitly; this small
    // wrapper covers labels added by late panels and language switches.
    (function(){
      function applyCatalogLabels(){
        if(typeof translatedCopy!=='function')return;
        document.querySelectorAll('[data-label-fa]').forEach(node=>{
          const source=node.dataset.labelFa||'';
          const value=translatedCopy(source);
          if(node.classList.contains('nav-btn')){
            const text=node.querySelector('.nav-text');
            if(text&&text.textContent!==value)text.textContent=value;
          }else if(node.children.length===0&&value&&node.textContent!==value)node.textContent=value;
        });
        try{translateStaticCopy()}catch(_){}
      }
      const legacy=window.setLanguage;
      if(typeof legacy==='function'){
        window.setLanguage=function(language){const result=legacy.call(this,language);applyCatalogLabels();return result};
        setLanguage=window.setLanguage;
      }
      applyCatalogLabels();
    })();
