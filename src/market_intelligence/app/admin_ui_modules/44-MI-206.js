
    // MI-206: expose the reviewed locale registry without changing the
    // existing FA/EN contracts. All selectable locales use the explicit
    // catalog pipeline for product copy.
    (function(){
      const names={en:'English',fa:'فارسی',tr:'Türkçe',ar:'العربية',es:'Español',it:'Italiano',de:'Deutsch'};
      const base=window.setLanguage||setLanguage;
      names.fr='Français';
      function ensureOptions(){document.querySelectorAll('[data-language-select]').forEach(select=>{Object.entries(names).forEach(([value,label])=>{if(!select.querySelector('option[value="'+value+'"]')){const option=document.createElement('option');option.value=value;option.textContent=label;select.appendChild(option)}});select.value=state.language})}
      function translateNewLocale(){if(state.language==='en'||state.language==='fa')return;translateTextNodes(document.body);document.querySelectorAll('[data-label-fa][data-label-en]').forEach(node=>{if(node.closest(reportProseSelector))return;const value=translatedCopy(node.dataset.labelFa||'');if(node.classList.contains('nav-btn')){const text=node.querySelector('.nav-text');if(text)text.textContent=value}else node.textContent=value});document.querySelectorAll('body *').forEach(node=>{if(node.children.length||node.closest('[data-language-select]')||node.closest(reportProseSelector))return;const raw=node.dataset.faText||node.textContent.trim();if(!raw)return;const key=node.dataset.faText||reverseCopyMap[raw]||raw;const translated=translatedCopy(key);if(translated&&translated!==raw)node.textContent=translated});const title=document.getElementById('pageTitle');if(title&&title.dataset.faText)title.textContent=translatedCopy(title.dataset.faText)}
      window.setLanguage=function(language){const value=supportedLanguages[language]?language:'en';const result=base.call(this,value);state.language=value;localStorage.setItem('research_bee_language',value);ensureOptions();document.documentElement.lang=value;document.documentElement.dir=supportedLanguages[value].dir;translateNewLocale();return result};setLanguage=window.setLanguage;ensureOptions();document.querySelectorAll('[data-language-select]').forEach(select=>select.addEventListener('change',event=>window.setLanguage(event.target.value)));translateNewLocale();
      // Restore a previously selected locale after the additive wrapper is
      // installed. This prevents the legacy FA/EN setter from collapsing a
      // stored tr/ar/es/it/de/fr preference during the first paint.
      if(storedLanguage&&supportedLanguages[storedLanguage]&&storedLanguage!==state.language)window.setLanguage(storedLanguage);
    })();
