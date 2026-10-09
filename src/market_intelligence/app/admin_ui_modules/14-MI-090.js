
    // MI-090/091/092/News List follow-up: keep the table schema identical to
    // the approved roadmap.  Older releases injected a Relevance score cell
    // here, which caused duplicate/misaligned headers after language changes.
    (function(){
      const syncPublicationHeaders=()=>{
        const header=document.querySelector('#view-content thead tr');
        if(!header)return;
        const label=window.__miLabel||((fa,en)=>state.language==='en'?en:fa);
        const labels=[label('خبر','News'),label('وضعیت انتشار','Publication status'),label('امتیاز ارتباط','Relevancy score'),label('منبع خبر','News source'),label('تاریخ خبر','News date'),label('انتشار در تلگرام','Telegram publication')];
        const selectAll=header.querySelector('th[data-publication-select-all]');
        header.replaceChildren();
        if(selectAll)header.appendChild(selectAll);
        labels.forEach((label,index)=>{const th=document.createElement('th');th.dataset.publicationColumn=String(index);th.textContent=label;header.appendChild(th)});
      };
      syncPublicationHeaders();
      const priorLanguage=setLanguage;
      setLanguage=function(lang){priorLanguage(lang);syncPublicationHeaders()};
      const version=document.getElementById('sidebarVersion');
      if(version&&version.textContent.includes('در حال بارگذاری'))version.textContent='v3.30.1';
    })();
