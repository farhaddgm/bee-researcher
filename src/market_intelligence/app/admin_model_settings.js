/* Per-assistant model settings. The server owns the supported model catalog. */
(function () {
  const copy = {
    fa: ['هوش مصنوعی دستیار', 'مدل تحلیل خبر', 'این مدل برای محاسبهٔ امتیاز ارتباط و تحلیل خبرهای همین دستیار استفاده می‌شود. تغییر پس از ذخیره، در اجراهای بعدی اعمال می‌شود؛ خبرهای قبلاً منتشرشده تغییر نمی‌کنند. مدل‌های مختلف هزینه و سرعت متفاوتی دارند. جستجوی رسانه تنظیم جداگانه دارد.', 'ذخیره مدل', 'مدل دستیار ذخیره شد', 'اتصال هوش مصنوعی پیکربندی نشده است؛ با مالک سرویس هماهنگ کنید.', 'ارائه‌دهنده', 'مدل را برای دستیار انتخاب‌شده تعیین کنید.'],
    en: ['Assistant AI', 'News analysis model', 'This model scores relevance and analyses news for this assistant. After saving, it applies to subsequent runs; already published news stays unchanged. Models differ in cost and speed. Media search has a separate configuration.', 'Save model', 'Assistant model saved', 'The AI connection is not configured; contact the service owner.', 'Provider', 'Choose the model for the selected assistant.'],
    tr: ['Asistanın yapay zekâsı', 'Haber analiz modeli', 'Bu model, bu asistanın haberlerini analiz eder ve ilgililik puanını hesaplar. Kaydettikten sonra sonraki çalıştırmalarda kullanılır; yayımlanmış haberler değişmez. Modellerin maliyeti ve hızı farklıdır. Medya araması ayrı yapılandırılır.', 'Modeli kaydet', 'Asistan modeli kaydedildi', 'Yapay zekâ bağlantısı yapılandırılmadı; hizmet sahibiyle iletişime geçin.', 'Sağlayıcı', 'Seçili asistanın modelini belirleyin.'],
    ar: ['الذكاء الاصطناعي للمساعد', 'نموذج تحليل الأخبار', 'يحسب هذا النموذج درجة الصلة ويحلل أخبار هذا المساعد. يُطبّق بعد الحفظ في التشغيلات التالية؛ ولا تتغير الأخبار المنشورة سابقًا. تختلف النماذج في التكلفة والسرعة. البحث عن المصادر له إعداد منفصل.', 'حفظ النموذج', 'تم حفظ نموذج المساعد', 'اتصال الذكاء الاصطناعي غير مُعدّ؛ تواصل مع مالك الخدمة.', 'المزوّد', 'اختر النموذج للمساعد المحدد.'],
    es: ['IA del asistente', 'Modelo de análisis de noticias', 'Este modelo calcula la relevancia y analiza las noticias de este asistente. Tras guardar, se usa en las siguientes ejecuciones; las noticias ya publicadas no cambian. Los modelos difieren en coste y velocidad. La búsqueda de medios se configura por separado.', 'Guardar modelo', 'Modelo del asistente guardado', 'La conexión de IA no está configurada; contacta con el propietario del servicio.', 'Proveedor', 'Elige el modelo del asistente seleccionado.'],
    it: ['IA dell’assistente', 'Modello di analisi delle notizie', 'Questo modello calcola la pertinenza e analizza le notizie di questo assistente. Dopo il salvataggio viene usato nelle esecuzioni successive; le notizie già pubblicate non cambiano. Costi e velocità variano tra i modelli. La ricerca delle fonti si configura separatamente.', 'Salva modello', 'Modello dell’assistente salvato', 'La connessione IA non è configurata; contatta il proprietario del servizio.', 'Fornitore', 'Scegli il modello dell’assistente selezionato.'],
    de: ['KI des Assistenten', 'Modell für die Nachrichtenanalyse', 'Dieses Modell bewertet die Relevanz und analysiert Nachrichten dieses Assistenten. Nach dem Speichern gilt es für spätere Durchläufe; veröffentlichte Nachrichten bleiben unverändert. Modelle unterscheiden sich in Kosten und Geschwindigkeit. Die Quellensuche wird separat konfiguriert.', 'Modell speichern', 'Assistentenmodell gespeichert', 'Die KI-Verbindung ist nicht eingerichtet; kontaktieren Sie den Diensteigentümer.', 'Anbieter', 'Wählen Sie das Modell für den ausgewählten Assistenten.'],
    fr: ['IA de l’assistant', 'Modèle d’analyse des actualités', 'Ce modèle évalue la pertinence et analyse les actualités de cet assistant. Après enregistrement, il est utilisé lors des prochaines exécutions ; les actualités déjà publiées restent inchangées. Le coût et la vitesse varient selon le modèle. La recherche de sources se configure séparément.', 'Enregistrer le modèle', 'Modèle de l’assistant enregistré', 'La connexion IA n’est pas configurée ; contactez le propriétaire du service.', 'Fournisseur', 'Choisissez le modèle de l’assistant sélectionné.']
  };
  const canWrite = () => Boolean(state.currentUser?.is_owner) || ['owner', 'admin', 'assistant_admin', 'editor'].includes(state.currentUser?.role);
  let draftAssistant = '', draftModel = '', dirty = false, saving = false;
  function render() {
    const root = $('view-settings');
    if (!root) return;
    let card = $('assistantAISettingsCard');
    if (!card) {
      card = document.createElement('section');
      card.id = 'assistantAISettingsCard';
      card.className = 'card section-card';
      card.setAttribute('data-dynamic-copy', '');
      card.innerHTML = '<div class="section-title"><h3 id="assistantAITitle"></h3></div><p id="assistantAIIntro" class="muted"></p><div class="form-grid"><div class="field"><label id="assistantAIProviderLabel" for="assistantAIProvider"></label><input id="assistantAIProvider" value="OpenAI · Responses API" readonly dir="ltr"></div><div class="field"><div class="label-info-row"><label id="analysisModelLabel" for="analysisModel"></label><button type="button" class="info-tip" id="analysisModelInfo" aria-describedby="analysisModelHelp">i<span id="analysisModelHelp" class="info-tip-popup" role="tooltip"></span></button></div><select id="analysisModel" dir="ltr"></select></div></div><p id="assistantAIConnectionNotice" class="muted" role="status"></p><div class="card-actions"><button type="button" class="btn primary" id="saveAnalysisModelBtn"></button></div>';
      root.insertBefore(card, root.querySelector('.page-head')?.nextSibling || root.firstChild);
      $('analysisModel').addEventListener('change', () => { draftModel = $('analysisModel').value; dirty = draftModel !== state.runtimeSettings?.analysis_model; render(); });
      $('saveAnalysisModelBtn').addEventListener('click', async () => {
        const id = state.assistantId, model = draftModel;
        if (saving || !id || draftAssistant !== id || !canWrite() || !dirty) return;
        saving = true; render();
        try {
          const result = await req('/admin/api/assistants/' + encodeURIComponent(id) + '/runtime-settings', { method: 'PUT', body: JSON.stringify({ analysis_model: model }) });
          if (id === state.assistantId) { state.runtimeSettings = result; dirty = false; draftModel = result.analysis_model; }
          toast((copy[state.language] || copy.en)[4]);
        } catch (error) { toast(friendlyError(error.message), true); }
        finally { saving = false; render(); }
      });
    }
    const c = copy[state.language] || copy.en;
    const runtime = state.runtimeSettings;
    const loaded = Boolean(state.assistantId && runtime?.assistant_id === state.assistantId);
    if (draftAssistant !== state.assistantId || !dirty) {
      if (draftAssistant !== state.assistantId) dirty = false;
      draftAssistant = state.assistantId;
      draftModel = loaded ? runtime.analysis_model : '';
    }
    const select = $('analysisModel');
    const options = loaded && Array.isArray(runtime.analysis_model_options) ? runtime.analysis_model_options : [];
    // Preserve a stored legacy/deployment model when it is outside the current
    // catalog. Never silently select the first option or reset it on reload.
    const choices = options.some(x => x.id === draftModel) || !draftModel ? options : [{ id: draftModel, label: draftModel }, ...options];
    const signature = JSON.stringify(choices);
    if (select.dataset.options !== signature) {
      select.replaceChildren(...choices.map(x => { const option = document.createElement('option'); option.value = x.id; option.textContent = x.label; return option; }));
      select.dataset.options = signature;
    }
    select.value = draftModel;
    select.disabled = !loaded || !canWrite() || saving;
    $('assistantAITitle').textContent = c[0];
    $('analysisModelLabel').textContent = c[1];
    $('analysisModelInfo').setAttribute('aria-label', c[1]);
    $('analysisModelHelp').textContent = c[2];
    $('assistantAIIntro').textContent = c[7];
    $('assistantAIProviderLabel').textContent = c[6];
    $('assistantAIConnectionNotice').textContent = loaded && !runtime.ai_analysis_ready ? c[5] : '';
    $('saveAnalysisModelBtn').textContent = c[3];
    $('saveAnalysisModelBtn').disabled = !loaded || !canWrite() || saving || !dirty || !options.some(x => x.id === draftModel);
    card.classList.toggle('hidden', !canWrite());
  }
  const priorLoad = loadAll;
  loadAll = async function () { try { return await priorLoad.apply(this, arguments); } finally { render(); } };
  const priorRefresh = refreshRuntimeSettingsUi;
  refreshRuntimeSettingsUi = async function () { try { return await priorRefresh.apply(this, arguments); } finally { render(); } };
  const priorLanguage = setLanguage;
  setLanguage = function () { const result = priorLanguage.apply(this, arguments); render(); return result; };
  window.setLanguage = setLanguage;
  const priorView = setView;
  setView = function () { const result = priorView.apply(this, arguments); render(); return result; };
  window.setView = setView;
  const priorVisibility = applyRoleVisibility;
  applyRoleVisibility = function () { const result = priorVisibility.apply(this, arguments); render(); return result; };
  render();
})();
