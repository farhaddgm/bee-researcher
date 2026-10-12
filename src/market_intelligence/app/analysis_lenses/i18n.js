/* One locale, loaded before controls; no delayed Persian fallback. */
(() => {
  'use strict';
  const keys='title|scope|focused|contextual|lens|analyze|analyzePrompt|related|days|refresh|more|none|coverage|selection|help|branch|loading|error|expired|budget|owner|enabled|savePolicy|defaultLens|create|name|definition|objective|dimensions|questions|priority|required|add|remove|up|down|saveDraft|preview|publish|restore|archive|revoke|reason|source|model|approved|pending|complete|history|high|normal|low|limitations|changed|referenceLanguage|private|helpDefinition|summary|quality|inScope|outScope|output|copy'.split('|');
  const rows={
    fa:'تحلیل خبر|دامنهٔ تحلیل|نقطه‌ای|هاله‌ای|لنز|تحلیل|این خبر را با لنز و منابع انتخاب‌شده تحلیل کن.|خبرهای مرتبط|بازهٔ روزها|بازخوانی|خبرهای دیگر|در منابع بررسی‌شده خبر مکمل کافی پیدا نشد.|پوشش بررسی|خبر انتخاب‌شده|لنز زاویهٔ بررسی را تغییر می‌دهد، نه واقعیت‌های خبر را. منابع مکمل باید انتخاب شوند.|این تغییر گفتگوی تازه می‌سازد و گفتگوی ذخیره‌نشده را حذف می‌کند. برای نگهداری آن، ابتدا ذخیره کنید. ادامه می‌دهید؟|در حال بارگذاری|درخواست انجام نشد؛ تنظیمات و دسترسی را بررسی کنید.|نشست یا پیش‌نمایش منقضی شده است.|سهمیه یا ظرفیت مدل کافی نیست.|فقط مالک|فعال|ذخیرهٔ تنظیمات|لنز پیش‌فرض|ساخت لنز|نام|تعریف|هدف|ابعاد|پرسش‌ها؛ هر سطر یک پرسش|اولویت|اطلاعات موردنیاز؛ هر سطر یک مورد|افزودن|حذف|بالا|پایین|ذخیرهٔ پیش‌نویس|پیش‌نمایش با AI؛ هزینه‌دار|فعال‌سازی نسخه|بازگردانی به پیش‌نویس|بایگانی|لغو نسخه|دلیل|خبر منتشرشده|مدل|نتیجه را بررسی کردم و تأیید می‌کنم.|در صف یا در حال تحلیل|تکمیل شد|تاریخچهٔ نسخه‌ها|بالا|معمولی|کم|محدودیت‌ها|منبع یا نسخه تغییر کرده؛ بازخوانی و تأیید دوباره لازم است.|زبان تعریف مرجع|پیش‌نمایش خصوصی است و از سهمیهٔ AI استفاده می‌کند.|تعریف و ابعاد چارچوب تحلیل‌اند؛ قواعد دقت، استناد و مجوز قابل حذف نیستند.|توضیح کوتاه|معیارهای کیفیت؛ هر سطر یک مورد|داخل دامنه؛ هر سطر یک مورد|خارج از دامنه؛ هر سطر یک مورد|بخش‌های خروجی|کپی لنز',
    en:'News analysis|Analysis scope|Focused|Contextual|Lens|Analyze|Analyze this news using the selected lens and sources.|Related reports|Window in days|Refresh|More reports|No sufficient related reports were found in the reviewed sources.|Coverage|Selected reports|A lens changes the questions, not the facts. Select any supplementary sources explicitly.|This starts a new conversation and deletes unsaved discussion. Save it first if you want to keep it. Continue?|Loading|Request failed; check settings and access.|Session or preview expired.|Insufficient quota or model capacity.|Owners only|Enabled|Save settings|Default lens|Create lens|Name|Definition|Objective|Dimensions|Questions; one per line|Priority|Required information; one per line|Add|Remove|Up|Down|Save draft|AI preview; uses budget|Publish revision|Restore as draft|Archive|Revoke revision|Reason|Published report|Model|I reviewed and approve this result.|Queued or analyzing|Completed|Revision history|High|Normal|Low|Limitations|Source or revision changed; refresh and confirm again.|Definition language|Preview is private and uses your AI budget.|Definitions guide analysis; accuracy, citations and access rules cannot be removed.|Short description|Quality criteria; one per line|In scope; one per line|Out of scope; one per line|Output sections|Copy lens',
    tr:'Haber analizi|Analiz kapsamı|Odaklı|Bağlamsal|Bakış açısı|Analiz et|Bu haberi seçilen bakış açısı ve kaynaklarla analiz et.|İlgili haberler|Gün aralığı|Yenile|Diğer haberler|İncelenen kaynaklarda yeterli ilgili haber bulunamadı.|Kapsam|Seçilen haberler|Bakış açısı soruları değiştirir, gerçekleri değil. Ek kaynakları açıkça seçin.|Bu işlem yeni bir sohbet başlatır ve kaydedilmemiş konuşmayı siler. Saklamak için önce kaydedin. Devam edilsin mi?|Yükleniyor|İstek başarısız; ayarları ve erişimi kontrol edin.|Oturum veya önizleme süresi doldu.|Kota veya model kapasitesi yetersiz.|Yalnızca sahipler|Etkin|Ayarları kaydet|Varsayılan bakış açısı|Bakış açısı oluştur|Ad|Tanım|Amaç|Boyutlar|Sorular; her satıra bir tane|Öncelik|Gerekli bilgiler; her satıra bir tane|Ekle|Kaldır|Yukarı|Aşağı|Taslağı kaydet|AI önizleme; bütçe kullanır|Sürümü etkinleştir|Taslak olarak geri yükle|Arşivle|Sürümü iptal et|Gerekçe|Yayımlanmış haber|Model|Sonucu inceledim ve onaylıyorum.|Sırada veya analiz ediliyor|Tamamlandı|Sürüm geçmişi|Yüksek|Normal|Düşük|Sınırlamalar|Kaynak veya sürüm değişti; yenileyip tekrar onaylayın.|Tanım dili|Önizleme özeldir ve AI bütçenizi kullanır.|Tanımlar analize rehberlik eder; doğruluk, kaynak ve erişim kuralları kaldırılamaz.|Kısa açıklama|Kalite ölçütleri; her satıra bir tane|Kapsama dahil; her satıra bir tane|Kapsam dışı; her satıra bir tane|Çıktı bölümleri|Bakış açısını kopyala',
    ar:'تحليل الخبر|نطاق التحليل|مركّز|سياقي|منظور التحليل|حلّل|حلّل هذا الخبر باستخدام المنظور والمصادر المختارة.|أخبار ذات صلة|الفترة بالأيام|تحديث|أخبار أخرى|لم يُعثر على أخبار مرتبطة كافية في المصادر المفحوصة.|التغطية|الأخبار المختارة|المنظور يغيّر الأسئلة لا الحقائق. اختر المصادر الإضافية صراحةً.|سيبدأ هذا محادثة جديدة ويحذف النقاش غير المحفوظ. احفظه أولاً إن أردت الاحتفاظ به. هل تريد المتابعة؟|جارٍ التحميل|فشل الطلب؛ تحقق من الإعدادات والصلاحيات.|انتهت الجلسة أو المعاينة.|الحصة أو سعة النموذج غير كافية.|للمالك فقط|مفعّل|حفظ الإعدادات|المنظور الافتراضي|إنشاء منظور|الاسم|التعريف|الهدف|الأبعاد|الأسئلة؛ سؤال في كل سطر|الأولوية|المعلومات المطلوبة؛ بند في كل سطر|إضافة|إزالة|أعلى|أسفل|حفظ المسودة|معاينة بالذكاء الاصطناعي؛ تستهلك الميزانية|تفعيل الإصدار|استعادة كمسودة|أرشفة|إلغاء الإصدار|السبب|خبر منشور|النموذج|راجعت النتيجة وأوافق عليها.|في الانتظار أو قيد التحليل|مكتمل|سجل الإصدارات|عالية|عادية|منخفضة|القيود|تغيّر المصدر أو الإصدار؛ حدّث وأكّد مجدداً.|لغة التعريف|المعاينة خاصة وتستهلك ميزانية الذكاء الاصطناعي.|التعريف يوجّه التحليل؛ لا يمكن حذف قواعد الدقة والاستشهاد والصلاحيات.|وصف مختصر|معايير الجودة؛ بند في كل سطر|ضمن النطاق؛ بند في كل سطر|خارج النطاق؛ بند في كل سطر|أقسام النتيجة|نسخ المنظور',
    es:'Análisis de noticias|Alcance del análisis|Enfocado|Contextual|Perspectiva|Analizar|Analiza esta noticia con la perspectiva y las fuentes seleccionadas.|Noticias relacionadas|Periodo en días|Actualizar|Más noticias|No se encontraron suficientes noticias relacionadas en las fuentes revisadas.|Cobertura|Noticias seleccionadas|La perspectiva cambia las preguntas, no los hechos. Selecciona explícitamente las fuentes adicionales.|Esto inicia una conversación nueva y elimina la no guardada. Guárdala antes si deseas conservarla. ¿Continuar?|Cargando|La solicitud falló; revisa la configuración y el acceso.|La sesión o la vista previa ha caducado.|Cuota o capacidad del modelo insuficiente.|Solo propietarios|Activado|Guardar configuración|Perspectiva predeterminada|Crear perspectiva|Nombre|Definición|Objetivo|Dimensiones|Preguntas; una por línea|Prioridad|Información necesaria; una por línea|Añadir|Eliminar|Arriba|Abajo|Guardar borrador|Vista previa con IA; consume presupuesto|Activar versión|Restaurar como borrador|Archivar|Revocar versión|Motivo|Noticia publicada|Modelo|He revisado y apruebo este resultado.|En cola o analizando|Completado|Historial de versiones|Alta|Normal|Baja|Limitaciones|La fuente o versión cambió; actualiza y confirma de nuevo.|Idioma de la definición|La vista previa es privada y consume tu presupuesto de IA.|Las definiciones guían el análisis; no pueden eliminarse las reglas de precisión, citas y acceso.|Descripción breve|Criterios de calidad; uno por línea|Dentro del alcance; uno por línea|Fuera del alcance; uno por línea|Secciones del resultado|Copiar perspectiva',
    it:'Analisi della notizia|Ambito dell’analisi|Mirata|Contestuale|Prospettiva|Analizza|Analizza questa notizia con la prospettiva e le fonti selezionate.|Notizie correlate|Periodo in giorni|Aggiorna|Altre notizie|Non sono state trovate notizie correlate sufficienti nelle fonti esaminate.|Copertura|Notizie selezionate|La prospettiva cambia le domande, non i fatti. Seleziona esplicitamente le fonti aggiuntive.|Avvia una nuova conversazione ed elimina quella non salvata. Salvala prima per conservarla. Continuare?|Caricamento|Richiesta non riuscita; controlla impostazioni e accesso.|Sessione o anteprima scaduta.|Quota o capacità del modello insufficiente.|Solo proprietari|Attivo|Salva impostazioni|Prospettiva predefinita|Crea prospettiva|Nome|Definizione|Obiettivo|Dimensioni|Domande; una per riga|Priorità|Informazioni necessarie; una per riga|Aggiungi|Rimuovi|Su|Giù|Salva bozza|Anteprima AI; usa il budget|Attiva versione|Ripristina come bozza|Archivia|Revoca versione|Motivo|Notizia pubblicata|Modello|Ho esaminato e approvo questo risultato.|In coda o in analisi|Completato|Cronologia delle versioni|Alta|Normale|Bassa|Limiti|Fonte o versione cambiata; aggiorna e conferma di nuovo.|Lingua della definizione|L’anteprima è privata e usa il budget AI.|Le definizioni guidano l’analisi; accuratezza, citazioni e accesso non possono essere rimossi.|Descrizione breve|Criteri di qualità; uno per riga|Nell’ambito; uno per riga|Fuori ambito; uno per riga|Sezioni del risultato|Copia prospettiva',
    de:'Nachrichtenanalyse|Analyseumfang|Fokussiert|Kontextbezogen|Perspektive|Analysieren|Analysiere diese Nachricht mit der gewählten Perspektive und den Quellen.|Verwandte Nachrichten|Zeitraum in Tagen|Aktualisieren|Weitere Nachrichten|In den geprüften Quellen wurden nicht genügend verwandte Nachrichten gefunden.|Abdeckung|Ausgewählte Nachrichten|Die Perspektive verändert die Fragen, nicht die Fakten. Zusätzliche Quellen ausdrücklich auswählen.|Dies startet ein neues Gespräch und löscht den ungespeicherten Verlauf. Zum Behalten zuerst speichern. Fortfahren?|Wird geladen|Anfrage fehlgeschlagen; Einstellungen und Zugriff prüfen.|Sitzung oder Vorschau abgelaufen.|Kontingent oder Modellkapazität reicht nicht aus.|Nur Eigentümer|Aktiviert|Einstellungen speichern|Standardperspektive|Perspektive erstellen|Name|Definition|Ziel|Dimensionen|Fragen; eine pro Zeile|Priorität|Benötigte Informationen; eine pro Zeile|Hinzufügen|Entfernen|Nach oben|Nach unten|Entwurf speichern|KI-Vorschau; nutzt Budget|Version aktivieren|Als Entwurf wiederherstellen|Archivieren|Version widerrufen|Grund|Veröffentlichte Nachricht|Modell|Ich habe das Ergebnis geprüft und bestätige es.|In Warteschlange oder Analyse|Abgeschlossen|Versionsverlauf|Hoch|Normal|Niedrig|Einschränkungen|Quelle oder Version geändert; aktualisieren und erneut bestätigen.|Sprache der Definition|Die Vorschau ist privat und nutzt Ihr KI-Budget.|Definitionen leiten die Analyse; Genauigkeit, Belege und Zugriffsregeln bleiben verbindlich.|Kurzbeschreibung|Qualitätskriterien; eines pro Zeile|Im Umfang; eines pro Zeile|Außerhalb des Umfangs; eines pro Zeile|Ergebnisabschnitte|Perspektive kopieren',
    fr:'Analyse de l’actualité|Périmètre d’analyse|Ciblée|Contextuelle|Perspective|Analyser|Analyse cette actualité avec la perspective et les sources choisies.|Actualités liées|Période en jours|Actualiser|Autres actualités|Aucune actualité liée suffisante n’a été trouvée dans les sources examinées.|Couverture|Actualités sélectionnées|La perspective change les questions, pas les faits. Sélectionnez explicitement les sources supplémentaires.|Cela démarre une nouvelle conversation et supprime l’échange non enregistré. Enregistrez-le d’abord pour le conserver. Continuer ?|Chargement|Échec de la demande ; vérifiez les paramètres et l’accès.|La session ou l’aperçu a expiré.|Quota ou capacité du modèle insuffisant.|Propriétaires uniquement|Activé|Enregistrer les paramètres|Perspective par défaut|Créer une perspective|Nom|Définition|Objectif|Dimensions|Questions ; une par ligne|Priorité|Informations nécessaires ; une par ligne|Ajouter|Supprimer|Monter|Descendre|Enregistrer le brouillon|Aperçu IA ; utilise le budget|Activer la version|Restaurer comme brouillon|Archiver|Révoquer la version|Motif|Actualité publiée|Modèle|J’ai examiné et j’approuve ce résultat.|En attente ou en cours d’analyse|Terminé|Historique des versions|Élevée|Normale|Faible|Limites|Source ou version modifiée ; actualisez et confirmez à nouveau.|Langue de la définition|L’aperçu est privé et utilise votre budget IA.|Les définitions guident l’analyse ; précision, citations et accès restent obligatoires.|Description courte|Critères de qualité ; un par ligne|Dans le périmètre ; un par ligne|Hors périmètre ; un par ligne|Sections du résultat|Copier la perspective'
  };
  const catalog=Object.fromEntries(Object.entries(rows).map(([language,text])=>{
    const values=text.split('|');if(values.length!==keys.length)throw new Error('Lens locale catalog mismatch: '+language);
    return [language,Object.fromEntries(keys.map((key,index)=>[key,values[index]]))];
  }));
  const extraKeys=["project","stop","draft","published","revoked","archived","replacement","examples","good","bad","translations","opportunities","risks","counterpoints","next_questions","suggested_checks","connections","shared_entity","shared_concept","shared_phrase","independenceUnknown","helpPriority","helpRequired","helpExamples","helpLabels","helpPreview","helpScope","helpQuality","helpQuestions"];
  const extraRows={
  "fa": [
    "پروژه",
    "توقف پیش‌نمایش",
    "پیش‌نویس",
    "فعال",
    "لغوشده",
    "بایگانی‌شده",
    "لنز جایگزین",
    "نمونه‌ها",
    "نمونهٔ مطلوب",
    "نمونهٔ نامطلوب",
    "نام و توضیح در زبان‌های دیگر",
    "فرصت‌ها",
    "ریسک‌ها",
    "دیدگاه مخالف",
    "پرسش‌های بعدی",
    "بررسی‌های پیشنهادی",
    "ارتباط خبرها",
    "موجودیت مشترک",
    "مفهوم مشترک",
    "عبارت مشترک",
    "استقلال منابع تأیید نشده است.",
    "اولویت، میزان توجه در تحلیل را تعیین می‌کند؛ امتیاز انتشار خبر را تغییر نمی‌دهد.",
    "اطلاعاتی که برای نتیجه‌گیری لازم است؛ نبود آن باید در پاسخ اعلام شود.",
    "حداکثر سه جفت نمونه؛ برای راهنمای بازبینی مالک‌اند و به مدل ارسال نمی‌شوند. دادهٔ محرمانه ننویسید.",
    "اختیاری است. ترجمهٔ نام و توضیح کوتاه را وارد کنید؛ با تغییر معنی تعریف، این ترجمه‌ها را هم بازبینی کنید.",
    "خبر منتشرشده و مدل را انتخاب کنید. پیش‌نمایش هزینه دارد و نتیجه تا تأیید مالک، لنز را فعال نمی‌کند.",
    "نقطه‌ای فقط خبر اصلی؛ هاله‌ای خبر اصلی و حداکثر چهار خبر مکملِ انتخاب‌شده را بررسی می‌کند.",
    "معیارهایی که هنگام تأیید پیش‌نمایش بررسی می‌کنید؛ یک معیار در هر سطر.",
    "پرسش‌های این بُعد که مدل باید بررسی کند؛ حداکثر پنج پرسش، هر کدام در یک سطر."
  ],
  "en": [
    "Project",
    "Stop preview",
    "Draft",
    "Published",
    "Revoked",
    "Archived",
    "Replacement lens",
    "Examples",
    "Good example",
    "Bad example",
    "Names and summaries in other languages",
    "Opportunities",
    "Risks",
    "Counterpoints",
    "Next questions",
    "Suggested checks",
    "Report connections",
    "Shared entity",
    "Shared concept",
    "Shared phrase",
    "Source independence has not been verified.",
    "Priority controls attention during analysis, not the publication relevance score.",
    "Information needed to reach a conclusion; its absence must be disclosed.",
    "At most three good/bad pairs, used for Owner review only, not sent to the model. Do not include confidential data.",
    "Optional. Translate the name and summary; review these translations whenever the definition changes meaning.",
    "Choose a published report and model. Preview uses budget and does not activate a lens without Owner approval.",
    "Focused uses the anchor only; contextual uses the anchor and up to four explicitly selected supplementary reports.",
    "Criteria you check when approving a preview; one per line.",
    "Questions for this dimension; at most five, one per line."
  ],
  "tr": [
    "Proje",
    "Önizlemeyi durdur",
    "Taslak",
    "Yayımlanmış",
    "İptal edilmiş",
    "Arşivlenmiş",
    "Yerine kullanılacak bakış açısı",
    "Örnekler",
    "İyi örnek",
    "Kötü örnek",
    "Diğer dillerde adlar ve özetler",
    "Fırsatlar",
    "Riskler",
    "Karşı görüşler",
    "Sonraki sorular",
    "Önerilen kontroller",
    "Haber bağlantıları",
    "Ortak varlık",
    "Ortak kavram",
    "Ortak ifade",
    "Kaynakların bağımsızlığı doğrulanmadı.",
    "Öncelik analizdeki dikkati belirler; yayın uygunluk puanını değiştirmez.",
    "Sonuca varmak için gerekli bilgiler; eksiklikleri açıklanmalıdır.",
    "En fazla üç iyi/kötü örnek çifti; yalnızca sahibin incelemesi içindir, modele gönderilmez. Gizli veri eklemeyin.",
    "İsteğe bağlıdır. Adı ve özeti çevirin; tanımın anlamı değiştiğinde çevirileri gözden geçirin.",
    "Yayımlanmış bir haber ve model seçin. Önizleme bütçe kullanır ve sahibin onayı olmadan bakış açısını etkinleştirmez.",
    "Odaklı analiz yalnızca ana haberi; bağlamsal analiz ana haberi ve açıkça seçilmiş en fazla dört ek haberi kullanır.",
    "Önizlemeyi onaylarken kontrol edeceğiniz ölçütler; her satıra bir tane.",
    "Bu boyutun soruları; en fazla beş, her satıra bir tane."
  ],
  "ar": [
    "المشروع",
    "إيقاف المعاينة",
    "مسودة",
    "منشور",
    "ملغى",
    "مؤرشف",
    "منظور بديل",
    "الأمثلة",
    "مثال جيد",
    "مثال سيئ",
    "الأسماء والملخصات بلغات أخرى",
    "الفرص",
    "المخاطر",
    "وجهات نظر معارضة",
    "الأسئلة التالية",
    "الفحوص المقترحة",
    "روابط الأخبار",
    "كيان مشترك",
    "مفهوم مشترك",
    "عبارة مشتركة",
    "لم يتم التحقق من استقلال المصادر.",
    "الأولوية تحدد الاهتمام أثناء التحليل، ولا تغيّر درجة الارتباط للنشر.",
    "المعلومات اللازمة للاستنتاج؛ يجب توضيح غيابها.",
    "ثلاثة أزواج جيدة/سيئة كحد أقصى، لمراجعة المالك فقط ولا تُرسل للنموذج. لا تُدرج بيانات سرية.",
    "اختياري. ترجم الاسم والملخص وراجع الترجمة عند تغيّر معنى التعريف.",
    "اختر خبراً منشوراً ونموذجاً. المعاينة تستهلك الميزانية ولا تفعّل المنظور دون موافقة المالك.",
    "التحليل المركّز يستخدم الخبر الأساسي فقط؛ والسياقي يستخدمه مع أربعة أخبار إضافية مختارة صراحةً كحد أقصى.",
    "المعايير التي تفحصها عند الموافقة على المعاينة؛ معيار في كل سطر.",
    "أسئلة هذا البعد؛ خمسة كحد أقصى، سؤال في كل سطر."
  ],
  "es": [
    "Proyecto",
    "Detener vista previa",
    "Borrador",
    "Publicado",
    "Revocado",
    "Archivado",
    "Perspectiva de reemplazo",
    "Ejemplos",
    "Buen ejemplo",
    "Mal ejemplo",
    "Nombres y resúmenes en otros idiomas",
    "Oportunidades",
    "Riesgos",
    "Contrapuntos",
    "Siguientes preguntas",
    "Comprobaciones sugeridas",
    "Conexiones entre noticias",
    "Entidad compartida",
    "Concepto compartido",
    "Frase compartida",
    "No se ha verificado la independencia de las fuentes.",
    "La prioridad guía la atención del análisis, no la puntuación de relevancia para publicar.",
    "Información necesaria para concluir; su ausencia debe indicarse.",
    "Hasta tres pares de ejemplos buenos/malos, solo para revisión del propietario; no se envían al modelo. No incluyas datos confidenciales.",
    "Opcional. Traduce el nombre y el resumen; revísalos cuando cambie el significado de la definición.",
    "Elige una noticia publicada y un modelo. La vista previa consume presupuesto y no activa la perspectiva sin aprobación del propietario.",
    "El análisis enfocado usa solo la noticia principal; el contextual añade hasta cuatro noticias seleccionadas explícitamente.",
    "Criterios que compruebas al aprobar la vista previa; uno por línea.",
    "Preguntas para esta dimensión; hasta cinco, una por línea."
  ],
  "it": [
    "Progetto",
    "Interrompi anteprima",
    "Bozza",
    "Pubblicato",
    "Revocato",
    "Archiviato",
    "Prospettiva sostitutiva",
    "Esempi",
    "Esempio corretto",
    "Esempio scorretto",
    "Nomi e descrizioni in altre lingue",
    "Opportunità",
    "Rischi",
    "Controargomentazioni",
    "Domande successive",
    "Verifiche suggerite",
    "Collegamenti tra notizie",
    "Entità condivisa",
    "Concetto condiviso",
    "Frase condivisa",
    "L’indipendenza delle fonti non è stata verificata.",
    "La priorità guida l’attenzione durante l’analisi, non il punteggio di rilevanza per la pubblicazione.",
    "Informazioni necessarie per una conclusione; la loro assenza deve essere dichiarata.",
    "Al massimo tre coppie di esempi corretti/scorretti, solo per la revisione del proprietario; non inviate al modello. Non inserire dati riservati.",
    "Facoltativo. Traduci nome e descrizione; rivedili quando cambia il significato della definizione.",
    "Scegli una notizia pubblicata e un modello. L’anteprima usa il budget e non attiva la prospettiva senza approvazione del proprietario.",
    "L’analisi mirata usa solo la notizia principale; quella contestuale aggiunge fino a quattro notizie selezionate esplicitamente.",
    "Criteri da controllare quando approvi l’anteprima; uno per riga.",
    "Domande per questa dimensione; al massimo cinque, una per riga."
  ],
  "de": [
    "Projekt",
    "Vorschau stoppen",
    "Entwurf",
    "Veröffentlicht",
    "Widerrufen",
    "Archiviert",
    "Ersatzperspektive",
    "Beispiele",
    "Gutes Beispiel",
    "Schlechtes Beispiel",
    "Namen und Beschreibungen in anderen Sprachen",
    "Chancen",
    "Risiken",
    "Gegenargumente",
    "Weitere Fragen",
    "Vorgeschlagene Prüfungen",
    "Nachrichtenverbindungen",
    "Gemeinsame Entität",
    "Gemeinsames Konzept",
    "Gemeinsame Formulierung",
    "Die Unabhängigkeit der Quellen wurde nicht überprüft.",
    "Die Priorität steuert die Aufmerksamkeit bei der Analyse, nicht den Relevanzwert für die Veröffentlichung.",
    "Für eine Schlussfolgerung benötigte Informationen; ihr Fehlen muss offengelegt werden.",
    "Höchstens drei gute/schlechte Beispielpaare, nur zur Prüfung durch Eigentümer; sie werden nicht an das Modell gesendet. Keine vertraulichen Daten eingeben.",
    "Optional. Namen und Beschreibung übersetzen; bei inhaltlichen Änderungen der Definition erneut prüfen.",
    "Veröffentlichte Nachricht und Modell wählen. Die Vorschau nutzt Budget und aktiviert die Perspektive erst nach Freigabe durch Eigentümer.",
    "Fokussiert nutzt nur die Hauptnachricht; kontextbezogen ergänzt bis zu vier ausdrücklich gewählte Nachrichten.",
    "Bei der Vorschaufreigabe zu prüfende Kriterien; eines pro Zeile.",
    "Fragen zu dieser Dimension; höchstens fünf, eine pro Zeile."
  ],
  "fr": [
    "Projet",
    "Arrêter l’aperçu",
    "Brouillon",
    "Publié",
    "Révoqué",
    "Archivé",
    "Perspective de remplacement",
    "Exemples",
    "Bon exemple",
    "Mauvais exemple",
    "Noms et descriptions dans d’autres langues",
    "Opportunités",
    "Risques",
    "Contrepoints",
    "Questions suivantes",
    "Vérifications suggérées",
    "Liens entre actualités",
    "Entité commune",
    "Concept commun",
    "Expression commune",
    "L’indépendance des sources n’a pas été vérifiée.",
    "La priorité guide l’attention de l’analyse, pas le score de pertinence pour la publication.",
    "Informations nécessaires pour conclure ; leur absence doit être signalée.",
    "Au plus trois paires de bons/mauvais exemples, pour la révision du propriétaire uniquement ; elles ne sont pas envoyées au modèle. N’incluez aucune donnée confidentielle.",
    "Facultatif. Traduisez le nom et la description ; revoyez-les lorsque le sens de la définition change.",
    "Choisissez une actualité publiée et un modèle. L’aperçu utilise le budget et n’active pas la perspective sans approbation du propriétaire.",
    "L’analyse ciblée utilise uniquement l’actualité principale ; la contextuelle ajoute au plus quatre actualités explicitement sélectionnées.",
    "Critères à vérifier lors de l’approbation de l’aperçu ; un par ligne.",
    "Questions pour cette dimension ; au plus cinq, une par ligne."
  ]
};
  for(const [language,values] of Object.entries(extraRows)){
    if(values.length!==extraKeys.length)throw new Error('Lens extended locale mismatch: '+language);
    Object.assign(catalog[language],Object.fromEntries(extraKeys.map((key,index)=>[key,values[index]])));
  }
  keys.push(...extraKeys);
  const compareKeys=['compareRevision','activeRevision','newDraft'];
  const compareRows={
  "fa": [
    "مقایسه با نسخهٔ فعال؛ دو درخواست AI",
    "نسخهٔ فعال",
    "پیش‌نویس جدید"
  ],
  "en": [
    "Compare with active revision; two AI requests",
    "Active revision",
    "New draft"
  ],
  "tr": [
    "Etkin sürümle karşılaştır; iki AI isteği",
    "Etkin sürüm",
    "Yeni taslak"
  ],
  "ar": [
    "مقارنة بالإصدار الفعّال؛ طلبان للذكاء الاصطناعي",
    "الإصدار الفعّال",
    "المسودة الجديدة"
  ],
  "es": [
    "Comparar con la versión activa; dos solicitudes de IA",
    "Versión activa",
    "Nuevo borrador"
  ],
  "it": [
    "Confronta con la versione attiva; due richieste AI",
    "Versione attiva",
    "Nuova bozza"
  ],
  "de": [
    "Mit aktiver Version vergleichen; zwei KI-Anfragen",
    "Aktive Version",
    "Neuer Entwurf"
  ],
  "fr": [
    "Comparer avec la version active ; deux requêtes IA",
    "Version active",
    "Nouveau brouillon"
  ]
};
  for(const [language,values] of Object.entries(compareRows))Object.assign(catalog[language],Object.fromEntries(compareKeys.map((key,index)=>[key,values[index]])));
  keys.push(...compareKeys);
  const matchKeys=['payments','fraud','voice_ai','agents','ransomware','personal_data','generative_video','chip_supply'];
  const matchRows={
  "fa": [
    "پردازش پرداخت",
    "تقلب پرداخت",
    "تشخیص گفتار",
    "عامل‌های هوش مصنوعی",
    "باج‌افزار",
    "حفاظت از دادهٔ شخصی",
    "تولید ویدیو",
    "تأمین نیمه‌هادی"
  ],
  "en": [
    "Payment processing",
    "Payment fraud",
    "Speech recognition",
    "AI agents",
    "Ransomware",
    "Personal data protection",
    "Video generation",
    "Semiconductor supply"
  ],
  "tr": [
    "Ödeme işleme",
    "Ödeme dolandırıcılığı",
    "Konuşma tanıma",
    "Yapay zekâ ajanları",
    "Fidye yazılımı",
    "Kişisel veri koruma",
    "Video üretimi",
    "Yarı iletken tedariki"
  ],
  "ar": [
    "معالجة المدفوعات",
    "احتيال الدفع",
    "التعرف على الكلام",
    "وكلاء الذكاء الاصطناعي",
    "برمجيات الفدية",
    "حماية البيانات الشخصية",
    "توليد الفيديو",
    "إمدادات أشباه الموصلات"
  ],
  "es": [
    "Procesamiento de pagos",
    "Fraude de pagos",
    "Reconocimiento de voz",
    "Agentes de IA",
    "Ransomware",
    "Protección de datos personales",
    "Generación de vídeo",
    "Suministro de semiconductores"
  ],
  "it": [
    "Elaborazione dei pagamenti",
    "Frode nei pagamenti",
    "Riconoscimento vocale",
    "Agenti IA",
    "Ransomware",
    "Protezione dei dati personali",
    "Generazione video",
    "Fornitura di semiconduttori"
  ],
  "de": [
    "Zahlungsabwicklung",
    "Zahlungsbetrug",
    "Spracherkennung",
    "KI-Agenten",
    "Ransomware",
    "Schutz personenbezogener Daten",
    "Videogenerierung",
    "Halbleiterversorgung"
  ],
  "fr": [
    "Traitement des paiements",
    "Fraude au paiement",
    "Reconnaissance vocale",
    "Agents IA",
    "Rançongiciel",
    "Protection des données personnelles",
    "Génération vidéo",
    "Approvisionnement en semi-conducteurs"
  ]
};
  for(const [language,values] of Object.entries(matchRows))Object.assign(catalog[language],Object.fromEntries(matchKeys.map((key,index)=>[key,values[index]])));
  keys.push(...matchKeys);
  catalog.fa.invalidDefinition="تعریف معتبر نیست؛ فیلدهای مشخص‌شده را اصلاح کنید.";
  catalog.en.invalidDefinition="Invalid definition; correct the indicated fields.";
  catalog.tr.invalidDefinition="Tanım geçersiz; belirtilen alanları düzeltin.";
  catalog.ar.invalidDefinition="التعريف غير صالح؛ صحّح الحقول المحددة.";
  catalog.es.invalidDefinition="Definición no válida; corrige los campos indicados.";
  catalog.it.invalidDefinition="Definizione non valida; correggi i campi indicati.";
  catalog.de.invalidDefinition="Ungültige Definition; markierte Felder korrigieren.";
  catalog.fr.invalidDefinition="Définition invalide ; corrigez les champs indiqués.";
  keys.push('invalidDefinition');
  const tokenKeys=['maxTokens','helpTokens'];
  const tokenRows={
  "fa": [
    "سقف توکن پاسخِ تحلیل ساختاریافته",
    "فقط تحلیل اولیهٔ لنز؛ شامل توکن‌های استدلال و پاسخ است و هزینه را افزایش می‌دهد. چت معمولی سقف قبلی خود را دارد. مقدار پیش‌فرض ۶۰۰۰ است."
  ],
  "en": [
    "Structured analysis output-token cap",
    "Initial lens analysis only, including reasoning and answer tokens; it increases the spend envelope. Ordinary chat retains its existing cap. Default: 6,000."
  ],
  "tr": [
    "Yapılandırılmış analiz çıktı token sınırı",
    "Yalnızca ilk bakış açısı analizi; akıl yürütme ve yanıt tokenlarını içerir, harcama üst sınırını artırır. Normal sohbetin sınırı değişmez. Varsayılan: 6.000."
  ],
  "ar": [
    "حد رموز خرج التحليل المنظّم",
    "للتحليل الأولي فقط، ويشمل رموز الاستدلال والإجابة ويزيد سقف التكلفة. يبقى حد المحادثة العادية دون تغيير. الافتراضي: ٦٠٠٠."
  ],
  "es": [
    "Límite de tokens de salida del análisis estructurado",
    "Solo el análisis inicial; incluye razonamiento y respuesta y aumenta el límite de gasto. El chat normal conserva su límite. Predeterminado: 6.000."
  ],
  "it": [
    "Limite token di uscita dell’analisi strutturata",
    "Solo analisi iniziale; include ragionamento e risposta e aumenta il limite di spesa. Il limite del normale chat resta invariato. Predefinito: 6.000."
  ],
  "de": [
    "Ausgabetoken-Limit für strukturierte Analysen",
    "Nur die erste Analyse, einschließlich Denk- und Antworttokens; erhöht den Kostenrahmen. Das Limit normaler Chats bleibt unverändert. Standard: 6.000."
  ],
  "fr": [
    "Plafond de tokens de sortie de l’analyse structurée",
    "Analyse initiale uniquement ; comprend raisonnement et réponse, et augmente le plafond de dépense. Le chat ordinaire conserve sa limite. Par défaut : 6 000."
  ]
};
  for(const [language,values] of Object.entries(tokenRows))Object.assign(catalog[language],Object.fromEntries(tokenKeys.map((key,index)=>[key,values[index]])));
  keys.push(...tokenKeys);
  catalog.fa.maxContext="سقف اندازهٔ زمینهٔ تحلیل (نویسه)";
  catalog.en.maxContext="Analysis context limit (characters)";
  catalog.tr.maxContext="Analiz bağlamı sınırı (karakter)";
  catalog.ar.maxContext="حد حجم سياق التحليل (محارف)";
  catalog.es.maxContext="Límite de contexto del análisis (caracteres)";
  catalog.it.maxContext="Limite contesto dell’analisi (caratteri)";
  catalog.de.maxContext="Analysekontext-Limit (Zeichen)";
  catalog.fr.maxContext="Limite du contexte d’analyse (caractères)";
  keys.push('maxContext');
  const failureKeys=['helpContext','contextLarge','modelLimit','invalidResult'];
  const failureRows={
  "fa": [
    "اندازهٔ ورودی، شامل منابع، چارچوب و schema خروجی است؛ متن بزرگ بدون برش پنهانی رد می‌شود. پیش‌فرض ۴۸۰۰۰ نویسه است و برای ادامهٔ گفتگو هم اعمال می‌شود.",
    "منابع یا زمینه برای این مدل بزرگ‌اند. منابع کمتری انتخاب کنید یا سقف تحلیل را با مالک بررسی کنید.",
    "پاسخ کامل در سقف مدل جا نشد؛ مدل یا سقف تحلیل را با مالک بررسی کنید. درخواست خودکار تکرار نشد.",
    "پاسخ ساختاریافته معتبر نبود و نمایش داده نشد؛ درخواست خودکار تکرار نشد."
  ],
  "en": [
    "Input includes sources, framework and output schema. Oversized context is rejected without hidden truncation. Default: 48,000 characters, including follow-up conversations.",
    "The selected context is too large. Select fewer sources or review the analysis cap with the Owner.",
    "The complete answer did not fit the model cap. Review the model or analysis cap with the Owner. No automatic retry occurred.",
    "The structured answer was invalid and was not displayed. No automatic retry occurred."
  ],
  "tr": [
    "Girdi kaynakları, çerçeveyi ve çıktı şemasını içerir. Aşırı bağlam gizlice kesilmeden reddedilir. Varsayılan: takip sohbetleri dahil 48.000 karakter.",
    "Seçilen bağlam çok büyük. Daha az kaynak seçin veya analiz sınırını sahip ile inceleyin.",
    "Tam yanıt model sınırına sığmadı. Modeli veya analiz sınırını sahip ile inceleyin. Otomatik yeniden deneme yapılmadı.",
    "Yapılandırılmış yanıt geçersizdi ve gösterilmedi. Otomatik yeniden deneme yapılmadı."
  ],
  "ar": [
    "يشمل الإدخال المصادر والإطار ومخطط المخرجات. يُرفض السياق الكبير دون اختصار خفي. الافتراضي ٤٨٠٠٠ محرف ويُطبق أيضاً على متابعة المحادثة.",
    "السياق المختار كبير جداً. اختر مصادر أقل أو راجع حد التحليل مع المالك.",
    "لم تسع الإجابة الكاملة ضمن حد النموذج. راجع النموذج أو حد التحليل مع المالك. لم تحدث إعادة تلقائية.",
    "الإجابة المنظّمة غير صالحة ولم تُعرض. لم تحدث إعادة تلقائية."
  ],
  "es": [
    "La entrada incluye fuentes, marco y esquema de salida. Un contexto excesivo se rechaza sin truncarlo. Predeterminado: 48.000 caracteres, incluidas las preguntas posteriores.",
    "El contexto seleccionado es demasiado grande. Selecciona menos fuentes o revisa el límite con el propietario.",
    "La respuesta completa no cabía en el límite del modelo. Revísalo con el propietario. No se reintentó automáticamente.",
    "La respuesta estructurada no era válida y no se mostró. No se reintentó automáticamente."
  ],
  "it": [
    "L’ingresso include fonti, quadro e schema di uscita. Un contesto eccessivo viene rifiutato senza tagli nascosti. Predefinito: 48.000 caratteri, anche per le domande successive.",
    "Il contesto è troppo grande. Seleziona meno fonti o verifica il limite con il proprietario.",
    "La risposta completa superava il limite del modello. Verifica modello o limite con il proprietario. Nessun tentativo automatico.",
    "La risposta strutturata non era valida e non è stata mostrata. Nessun tentativo automatico."
  ],
  "de": [
    "Die Eingabe umfasst Quellen, Rahmen und Ausgabeschema. Zu großer Kontext wird ohne heimliche Kürzung abgelehnt. Standard: 48.000 Zeichen, auch für Folgefragen.",
    "Der Kontext ist zu groß. Weniger Quellen wählen oder das Analyselimit mit dem Eigentümer prüfen.",
    "Die vollständige Antwort passte nicht ins Modelllimit. Modell oder Analyselimit mit dem Eigentümer prüfen. Keine automatische Wiederholung.",
    "Die strukturierte Antwort war ungültig und wurde nicht angezeigt. Keine automatische Wiederholung."
  ],
  "fr": [
    "L’entrée comprend sources, cadre et schéma de sortie. Un contexte trop grand est refusé sans coupe cachée. Par défaut : 48 000 caractères, y compris les questions suivantes.",
    "Le contexte est trop grand. Choisissez moins de sources ou examinez le plafond avec le propriétaire.",
    "La réponse complète dépassait le plafond du modèle. Examinez modèle ou plafond avec le propriétaire. Aucun nouvel essai automatique.",
    "La réponse structurée était invalide et n’a pas été affichée. Aucun nouvel essai automatique."
  ]
};
  for(const [language,values] of Object.entries(failureRows))Object.assign(catalog[language],Object.fromEntries(failureKeys.map((key,index)=>[key,values[index]])));
  keys.push(...failureKeys);
  const entityNames={openai:'OpenAI',anthropic:'Anthropic',microsoft:'Microsoft',google:'Google',nvidia:'NVIDIA',elevenlabs:'ElevenLabs'};
  const lang=()=>document.documentElement.lang?.split('-')[0]||'en';
  const t=key=>catalog[lang()]?.[key]||catalog.en[key]||entityNames[key]||key;
  const id=()=>crypto.randomUUID?.()||'lens-'+[...crypto.getRandomValues(new Uint32Array(4))].map(v=>v.toString(16).padStart(8,'0')).join('-');
  window.BeeLensI18n={t,lang,catalog,keys,id};
})();
