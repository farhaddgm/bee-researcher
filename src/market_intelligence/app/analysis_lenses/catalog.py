"""Immutable v1 seed. Change future templates through NEW seed versions."""
import uuid

from app.analysis_lenses.schemas import Definition

NAMESPACE = uuid.UUID('e542daab-8bbf-4e16-82f5-377017190001')
NAMES = {
    'fa': ['عمومی', 'مارکتینگ', 'امنیت', 'محصول'],
    'en': ['General', 'Marketing', 'Security', 'Product'],
    'tr': ['Genel', 'Pazarlama', 'Güvenlik', 'Ürün'],
    'ar': ['عام', 'التسويق', 'الأمن', 'المنتج'],
    'es': ['General', 'Marketing', 'Seguridad', 'Producto'],
    'it': ['Generale', 'Marketing', 'Sicurezza', 'Prodotto'],
    'de': ['Allgemein', 'Marketing', 'Sicherheit', 'Produkt'],
    'fr': ['Général', 'Marketing', 'Sécurité', 'Produit'],
}
SUMMARIES = {
    'fa': ['فهم خبر، تغییر اصلی، پیامدهای مستقیم و ابهام‌ها.', 'بررسی نیاز مشتری، بازار، جایگاه برند و فرضیه‌های قابل آزمایش.', 'بررسی دفاعی داده، دسترسی، وابستگی و تداوم خدمت؛ بدون فرض وجود تهدید.', 'بررسی مسئلهٔ کاربر، ارزش محصول، وابستگی‌ها و آزمایش‌های توسعه.'],
    'en': ['Understand the news, reported change, direct consequences and uncertainty.', 'Assess customer needs, markets, positioning and testable hypotheses.', 'Defensively assess data, access, dependencies and continuity without assuming a threat.', 'Assess user problems, product value, dependencies and development experiments.'],
    'tr': ['Haberi, değişimi, doğrudan sonuçları ve belirsizlikleri anlayın.', 'Müşteri ihtiyaçlarını, pazarı, konumlandırmayı ve test edilebilir varsayımları inceleyin.', 'Tehdit varsaymadan veri, erişim, bağımlılıklar ve sürekliliği savunma açısından inceleyin.', 'Kullanıcı sorunlarını, ürün değerini, bağımlılıkları ve geliştirme deneylerini inceleyin.'],
    'ar': ['فهم الخبر والتغيير والنتائج المباشرة وأوجه الغموض.', 'دراسة احتياجات العملاء والسوق والتموضع والفرضيات القابلة للاختبار.', 'فحص دفاعي للبيانات والوصول والاعتماديات واستمرارية الخدمة دون افتراض وجود تهديد.', 'دراسة مشكلة المستخدم وقيمة المنتج والاعتماديات وتجارب التطوير.'],
    'es': ['Comprende la noticia, el cambio, las consecuencias directas y la incertidumbre.', 'Examina clientes, mercado, posicionamiento e hipótesis comprobables.', 'Examina datos, acceso, dependencias y continuidad sin presuponer amenazas.', 'Examina problemas del usuario, valor del producto, dependencias y experimentos.'],
    'it': ['Comprendi notizia, cambiamento, conseguenze dirette e incertezze.', 'Esamina clienti, mercato, posizionamento e ipotesi verificabili.', 'Esamina dati, accesso, dipendenze e continuità senza presumere minacce.', 'Esamina problemi degli utenti, valore del prodotto, dipendenze ed esperimenti.'],
    'de': ['Nachricht, Veränderung, direkte Folgen und Unsicherheiten verstehen.', 'Kundenbedarf, Markt, Positionierung und prüfbare Hypothesen untersuchen.', 'Daten, Zugriff, Abhängigkeiten und Kontinuität defensiv prüfen, ohne Bedrohungen vorauszusetzen.', 'Nutzerprobleme, Produktwert, Abhängigkeiten und Entwicklungsversuche untersuchen.'],
    'fr': ['Comprendre l’actualité, le changement, les conséquences directes et les incertitudes.', 'Examiner les clients, le marché, le positionnement et les hypothèses testables.', 'Examiner données, accès, dépendances et continuité sans présumer une menace.', 'Examiner les problèmes utilisateurs, la valeur produit, les dépendances et les expérimentations.'],
}
TEMPLATES_V1 = {
    'general': ('Understand the reported change, stakeholders, direct consequences and uncertainty without forcing a positive or negative conclusion.', [
        ('event_change', 'Reported change', 'high', 'What actually changed? Distinguish announcement, event date and publication date.'),
        ('stakeholders', 'Stakeholders', 'normal', 'Who is explicitly affected? Separate named groups from hypotheses.'),
        ('consequences', 'Direct consequences', 'normal', 'What mechanism could create an effect, and under what conditions?'),
        ('uncertainty', 'Uncertainty', 'high', 'What is unverified or missing? What evidence would change the conclusion?')]),
    'marketing': ('Analyze evidence-backed changes in customer needs, market behavior, positioning and value; suggest testable marketing hypotheses, not guaranteed sales growth.', [
        ('customer_need', 'Customer need', 'high', 'What customer need or expectation may change? Distinguish observed behavior from supplier claims.'),
        ('segments', 'Market segments', 'normal', 'Which segment might be affected, and why? Do not invent market size or company personas.'),
        ('positioning', 'Positioning and competition', 'high', 'What differentiation is supported by selected reports? Do not invent competitors or leadership.'),
        ('value_pricing', 'Value and pricing', 'normal', 'What could change perceived value or adoption cost? Unknown prices and margins remain unknown.'),
        ('messaging_channels', 'Messaging and channels', 'normal', 'What messaging or channel hypothesis follows from the evidence? Do not invent campaign budgets.'),
        ('experiments', 'Experiments', 'high', 'What small experiment and observable metric could test a hypothesis? Never predict its result.')]),
    'security': ('Defensively assess cybersecurity, data protection, access, dependencies and service continuity. Do not assume that a vulnerability, breach or threat exists.', [
        ('assets_data', 'Data and assets', 'high', 'Which data or assets are explicitly involved? Do not assume the user company uses this system.'),
        ('exposure', 'Exposure and access', 'high', 'Is a change in exposure supported? A technology name alone is not a vulnerability.'),
        ('dependencies', 'Dependencies', 'normal', 'Which supplier or infrastructure dependency is supported, and under what conditions?'),
        ('privacy', 'Privacy', 'high', 'What data transfer or retention is stated? Separate promised policy from verified implementation.'),
        ('continuity', 'Continuity', 'normal', 'Is an outage or operational change documented? Company impact depends on supplied architecture.'),
        ('defensive_checks', 'Defensive checks', 'high', 'What safe, proportionate defensive check is justified? Never invent CVEs, attackers or breach severity.')]),
    'product': ('Assess user problems, product value, dependencies and testable development hypotheses; never turn every news item into a mandatory feature or automatically change a roadmap.', [
        ('user_problem', 'User problem', 'high', 'Which user job or problem is addressed? Claimed demand is not verified user research.'),
        ('product_value', 'Product value', 'high', 'What value or differentiation is supported by the selected reports, not an imagined whole market?'),
        ('feasibility', 'Feasibility', 'normal', 'What data, infrastructure or permissions are needed? Do not invent engineering time or team capacity.'),
        ('experience_tradeoffs', 'Experience and trade-offs', 'normal', 'What user benefit and experience cost may follow? Separate facts from assumptions.'),
        ('validation', 'Validation', 'high', 'What smallest useful test could falsify the hypothesis? Do not invent numeric success targets.'),
        ('prioritization', 'Conditional priority', 'normal', 'What information is needed for build versus do-not-build? No automatic assignment or roadmap change.')]),
}


def initial_definitions() -> list[tuple[str, Definition]]:
    values = []
    for index, (key, (description, dims)) in enumerate(TEMPLATES_V1.items()):
        definition = Definition.model_validate({'name': NAMES['en'][index], 'summary': description[:240], 'definition': description,
            'objective': 'Help the reader identify evidence, uncertainties and a useful next question or test.',
            'out_of_scope': ['Inventing facts, numbers, sources or private company details.', 'Changing publication, access, model or administrative settings.'],
            'dimensions': [{'key': k, 'name': n, 'description': q, 'questions': [q], 'priority': p} for k, n, p, q in dims],
            'quality_criteria': ['Link conclusions to supplied evidence.', 'Separate report claims, hypotheses and missing information.', 'Do not force opportunities, risks or findings for irrelevant dimensions.'],
            'localized_labels': {lang: {'name': names[index], 'summary': SUMMARIES[lang][index]} for lang, names in NAMES.items()}})
        values.append((key, definition))
    return values
