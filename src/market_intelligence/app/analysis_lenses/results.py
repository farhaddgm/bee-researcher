import json

from app.analysis_lenses.schemas import Definition, Result

HEADINGS = {
    'fa': ['جمع‌بندی', 'ادعاهای گزارش‌شده', 'تحلیل ابعاد', 'فرصت‌ها', 'ریسک‌ها', 'نگاه مخالف', 'پرسش‌های بعدی', 'بررسی پیشنهادی', 'محدودیت‌ها', 'ارتباط منابع'],
    'en': ['Summary', 'Reported claims', 'Dimensions', 'Opportunities', 'Risks', 'Counterpoints', 'Next questions', 'Suggested checks', 'Limitations', 'Source connections'],
    'tr': ['Özet', 'Bildirilen iddialar', 'Boyutlar', 'Fırsatlar', 'Riskler', 'Karşı görüşler', 'Sonraki sorular', 'Önerilen kontroller', 'Sınırlamalar', 'Kaynak bağlantıları'],
    'ar': ['ملخص', 'الادعاءات الواردة', 'أبعاد التحليل', 'الفرص', 'المخاطر', 'وجهات نظر مخالفة', 'الأسئلة التالية', 'فحوص مقترحة', 'القيود', 'روابط المصادر'],
    'es': ['Resumen', 'Afirmaciones publicadas', 'Dimensiones', 'Oportunidades', 'Riesgos', 'Contrapuntos', 'Próximas preguntas', 'Comprobaciones sugeridas', 'Limitaciones', 'Relaciones entre fuentes'],
    'it': ['Sintesi', 'Affermazioni riportate', 'Dimensioni', 'Opportunità', 'Rischi', 'Controargomentazioni', 'Prossime domande', 'Verifiche suggerite', 'Limiti', 'Relazioni tra fonti'],
    'de': ['Zusammenfassung', 'Berichtete Aussagen', 'Dimensionen', 'Chancen', 'Risiken', 'Gegenargumente', 'Weitere Fragen', 'Empfohlene Prüfungen', 'Einschränkungen', 'Quellenbeziehungen'],
    'fr': ['Synthèse', 'Affirmations rapportées', 'Dimensions', 'Opportunités', 'Risques', 'Contre-arguments', 'Questions suivantes', 'Vérifications proposées', 'Limites', 'Relations entre sources'],
}
DETAILS = {
    'fa': ['دارای شاهد', 'شواهد محدود', 'اطلاعات ناکافی', 'نامرتبط با دادهٔ موجود', 'فرضیات', 'اطلاعات ناقص', 'استنباط مشروط'],
    'en': ['Supported', 'Limited evidence', 'Insufficient information', 'Not applicable', 'Assumptions', 'Missing information', 'Conditional inference'],
    'tr': ['Destekleniyor', 'Sınırlı kanıt', 'Yetersiz bilgi', 'Uygulanamaz', 'Varsayımlar', 'Eksik bilgiler', 'Koşullu çıkarım'],
    'ar': ['مدعوم', 'أدلة محدودة', 'معلومات غير كافية', 'غير منطبق', 'افتراضات', 'معلومات ناقصة', 'استنتاج مشروط'],
    'es': ['Con respaldo', 'Pruebas limitadas', 'Información insuficiente', 'No aplicable', 'Supuestos', 'Información faltante', 'Inferencia condicional'],
    'it': ['Supportato', 'Prove limitate', 'Informazioni insufficienti', 'Non applicabile', 'Ipotesi', 'Informazioni mancanti', 'Inferenza condizionale'],
    'de': ['Belegt', 'Begrenzte Belege', 'Unzureichende Informationen', 'Nicht zutreffend', 'Annahmen', 'Fehlende Informationen', 'Bedingte Schlussfolgerung'],
    'fr': ['Étayé', 'Preuves limitées', 'Informations insuffisantes', 'Non applicable', 'Hypothèses', 'Informations manquantes', 'Inférence conditionnelle'],
}


def validate(raw: str, context: dict, language: str) -> tuple[dict, str]:
    result = Result.model_validate(json.loads(raw))
    definition = Definition.model_validate(context['_analysis']['definition'])
    dimensions = {d.key: d for d in definition.dimensions if d.enabled}
    found = [d.dimension for d in result.dimensions]
    if len(found) != len(set(found)) or set(found) != set(dimensions):
        raise ValueError('analysis dimension mismatch')
    source_segments = {s['id']: s['text'] for s in context['segments']}
    citations = set(source_segments)
    for value in result.reported_claims + result.dimensions + result.opportunities + result.risks + result.connections:
        if set(value.citations) - citations:
            raise ValueError('analysis citation mismatch')
        if getattr(value, 'status', None) == 'supported' and not value.citations:
            raise ValueError('supported finding needs evidence')
        if hasattr(value, 'dimension') and value.dimension not in dimensions:
            raise ValueError('inactive or unknown dimension')
    if any(not any(claim.quote in source_segments[sid] for sid in claim.citations) for claim in result.reported_claims):
        raise ValueError('claim quote not present in cited evidence')
    selected = set(context.get('source_ids', []))
    if any(str(c.publication_id) not in selected for c in result.connections):
        raise ValueError('connection outside supplied sources')
    if context['_analysis']['scope'] == 'focused' and result.connections:
        raise ValueError('focused analysis cannot include external connections')
    def cited(text, ids):
        return text + ''.join(' [' + sid + ']' for sid in dict.fromkeys(ids))
    labels = HEADINGS[language]
    details = DETAILS[language]
    statuses = dict(zip(('supported', 'limited', 'insufficient', 'not_applicable'), details[:4]))
    def finding(value):
        text = value.heading + ' — ' + statuses[value.status] + '\n' + cited(value.finding, value.citations)
        if value.assumptions:
            text += '\n' + details[4] + ': ' + '; '.join(value.assumptions)
        if value.gaps:
            text += '\n' + details[5] + ': ' + '; '.join(value.gaps)
        return text
    def effect(value):
        support = {'adequate': details[0], 'limited': details[1], 'insufficient': details[2]}[value.support]
        return details[6] + ' — ' + support + '\n' + cited(value.text + '\n' + value.mechanism + '\n' + '\n'.join(value.conditions), value.citations)
    sections = [(labels[0], [result.summary]), (labels[1], [cited(x.text, x.citations) for x in result.reported_claims]),
                (labels[2], [finding(x) for x in result.dimensions])]
    optional = {
        'opportunities': (labels[3], [effect(x) for x in result.opportunities]),
        'risks': (labels[4], [effect(x) for x in result.risks]),
        'counterpoints': (labels[5], result.counterpoints), 'next_questions': (labels[6], result.next_questions),
        'suggested_checks': (labels[7], result.suggested_checks),
        'connections': (labels[9], [cited(x.explanation, x.citations) for x in result.connections]),
    }
    sections += [optional[key] for key in definition.output_sections]
    sections.append((labels[8], result.limitations))
    rendered = '\n\n'.join(name + '\n' + '\n\n'.join(values) for name, values in sections if values)
    if len(rendered) > 40000:
        raise ValueError('rendered result too large')
    return result.model_dump(mode='json'), rendered
