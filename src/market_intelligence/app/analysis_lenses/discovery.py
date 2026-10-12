"""Bounded multilingual concept matching; not an independent web search."""
import re
import unicodedata
from collections import Counter

CONCEPTS = {
    'payments': ('payment processing', 'پردازش پرداخت', 'پرداخت الکترونیک', 'معالجة المدفوعات', 'ödeme işleme', 'procesamiento de pagos', 'elaborazione dei pagamenti', 'Zahlungsabwicklung', 'traitement des paiements'),
    'fraud': ('payment fraud', 'تقلب پرداخت', 'احتيال الدفع', 'ödeme dolandırıcılığı', 'fraude de pagos', 'frode nei pagamenti', 'Zahlungsbetrug', 'fraude au paiement'),
    'voice_ai': ('speech recognition', 'تشخیص گفتار', 'التعرف على الكلام', 'konuşma tanıma', 'reconocimiento de voz', 'riconoscimento vocale', 'Spracherkennung', 'reconnaissance vocale'),
    'agents': ('ai agent', 'ai agents', 'عامل هوش مصنوعی', 'عامل‌های هوش مصنوعی', 'وكلاء الذكاء الاصطناعي', 'yapay zekâ ajan', 'agentes de ia', 'agenti ia', 'ki-agenten', 'agents ia'),
    'ransomware': ('ransomware', 'باج افزار', 'باج‌افزار', 'برمجيات الفدية', 'fidye yazılımı', 'ransomiciel'),
    'personal_data': ('personal data protection', 'حفاظت داده شخصی', 'حماية البيانات الشخصية', 'kişisel veri koruma', 'protección de datos personales', 'protezione dei dati personali', 'personenbezogener Datenschutz', 'protection des données personnelles'),
    'generative_video': ('video generation', 'تولید ویدیو', 'تولید ویدئو', 'توليد الفيديو', 'video üretimi', 'generación de vídeo', 'generazione video', 'Videogenerierung', 'génération vidéo'),
    'chip_supply': ('semiconductor supply', 'تأمین نیمه هادی', 'تامین نیمه‌هادی', 'إمدادات أشباه الموصلات', 'yarı iletken tedariki', 'suministro de semiconductores', 'fornitura di semiconduttori', 'Halbleiterversorgung', 'approvisionnement en semi-conducteurs'),
}
ENTITIES = {
    'openai': ('openai', 'اوپن ای آی', 'اوپن‌ای‌آی'), 'anthropic': ('anthropic', 'آنتروپیک'),
    'microsoft': ('microsoft', 'مایکروسافت', 'مايكروسوفت'), 'google': ('google', 'گوگل', 'جوجل'),
    'nvidia': ('nvidia', 'انویدیا', 'إنفيديا'), 'elevenlabs': ('elevenlabs', 'الون لبز'),
}
STOP = set('the and that this with from have been will news report source https www com org article about into for are was were its new latest published company analysis summary'.split())
STOP.update('این برای خبر گزارش منبع درباره توسط شده شود بود است هستند خواهد شرکت تحلیل خلاصه'.split())
STOP.update('und die der das mit von eine einer über ist sind nach aus durch'.split())
STOP.update('les des une dans pour avec sur est sont cette rapport source actualité'.split())
STOP.update('para una del las los con por que esta sono della delle della degli notizia fonte'.split())
STOP.update('bir ile için haber kaynak olan yeni هذه هذا التي الذي على إلى عن مصدر خبر'.split())


def phrases(text: str) -> set[str]:
    # Headline/lead only: repeated publisher footers are not topic evidence.
    tokens = re.findall(r'[^\W\d_]{3,}', normalized(text[:700]))
    return {' '.join(tokens[i:i+size]) for size in (2, 3) for i in range(len(tokens)-size+1)
            if all(v not in STOP for v in tokens[i:i+size])}


def normalized(text: str) -> str:
    text = unicodedata.normalize('NFC', text).casefold().translate(str.maketrans('يك', 'یک')).replace('\u200c', ' ')
    text = re.sub(r'[\u064b-\u065f\u0670]', '', text)
    return ' '.join(text.split())


def present(text: str, alias: str) -> bool:
    return bool(re.search(r'(?<!\w)' + re.escape(normalized(alias)) + r'(?!\w)', text))


def features(text: str) -> tuple[set[str], set[str]]:
    value = normalized(text)
    return ({key for key, aliases in CONCEPTS.items() if any(present(value, a) for a in aliases)},
            {key for key, aliases in ENTITIES.items() if any(present(value, a) for a in aliases)})


def rank(anchor: str, rows: list[dict]) -> list[dict]:
    concepts, entities = features(anchor)
    anchor_phrases = phrases(anchor)
    counts = Counter(v for row in rows for v in phrases(row['text']))
    seen = {normalized(anchor)}
    selected = []
    for row in rows:
        text = normalized(row['text'])
        if text in seen:
            continue
        seen.add(text)
        other_concepts, other_entities = features(row['text'])
        common_concepts, common_entities = concepts & other_concepts, entities & other_entities
        common_phrases = {v for v in anchor_phrases & phrases(row['text']) if counts[v] <= max(2, len(rows) // 10)}
        if not common_concepts and not common_entities and not common_phrases:
            continue
        selected.append({**row, 'relationship': 'shared_entity' if common_entities else 'shared_concept' if common_concepts else 'shared_phrase',
                         'matches': sorted(common_entities | common_concepts | common_phrases)[:8],
                         'score': len(common_entities) * 40 + len(common_concepts) * 15 + min(len(common_phrases), 5) * 4,
                         'independent': None})
    # Stable tie breaking, never randomness that silently changes selections.
    selected.sort(key=lambda x: (x['published_at'], x['id']), reverse=True)
    return sorted(selected, key=lambda x: -x['score'])[:50]
