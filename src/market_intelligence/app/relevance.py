from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


PERSIAN_TRANSLATION = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")
NON_WORD = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)
STOP_WORDS = {
    "از",
    "به",
    "در",
    "با",
    "برای",
    "که",
    "این",
    "آن",
    "را",
    "و",
    "یا",
    "یک",
    "شد",
    "شده",
    "می",
    "است",
    "بر",
    "تا",
    "های",
    "خبر",
}
FINANCE_ANCHORS = {
    "بانک",
    "بانکی",
    "بانکداری",
    "بانک مرکزی",
    "مالی",
    "فین تک",
    "پرداخت الکترونیک",
    "شاپرک",
    "شتاب",
    "کارتخوان",
    "درگاه پرداخت",
    "بورس",
    "بیمه",
    "وام",
    "تسهیلات",
    "سپرده",
    "پولشویی",
    "نئوبانک",
    "موبایل بانک",
    "اینترنت بانک",
    "اعتبارسنجی",
}
GENERIC_TOPIC_TERMS = {
    "پرداخت",
    "مالی",
    "قانون",
    "مصوبه",
    "دستورالعمل",
    "مقررات",
    "الزام",
    "اعتبار",
}


def normalize_text(value: str) -> str:
    value = DIACRITICS.sub("", value.translate(PERSIAN_TRANSLATION).lower())
    return " ".join(NON_WORD.sub(" ", value).split())


def title_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in normalize_text(value).split()
        if len(token) > 1 and token not in STOP_WORDS
    )


def _term_matches(normalized_value: str, normalized_term: str) -> list[str]:
    if not normalized_term:
        return []
    pattern = rf"(?:^|\s){re.escape(normalized_term)}(?:\s|$)"
    return re.findall(pattern, normalized_value)


def _contains_term(normalized_value: str, normalized_term: str) -> bool:
    return bool(_term_matches(normalized_value, normalized_term))


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = title_tokens(left)
    right_tokens = title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def cluster_key(title: str) -> str:
    tokens = sorted(title_tokens(title))
    basis = " ".join(tokens) or normalize_text(title)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TopicScore:
    lexical_score: float
    semantic_score: float | None
    combined_score: float
    positive_matches: tuple[str, ...]
    negative_matches: tuple[str, ...]
    explanation: str
    selected: bool


def lexical_topic_score(
    *,
    title: str,
    text: str,
    positive_terms: list[str],
    negative_terms: list[str],
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    normalized_title = normalize_text(title)
    normalized_text = normalize_text(text)
    positive: list[str] = []
    title_hits = 0
    frequency = 0
    for term in positive_terms:
        normalized_term = normalize_text(str(term))
        if not normalized_term:
            continue
        count = len(_term_matches(normalized_text, normalized_term))
        in_title = _contains_term(normalized_title, normalized_term)
        if count or in_title:
            positive.append(str(term))
            frequency += min(count, 4)
            title_hits += int(in_title)
    negative = tuple(
        str(term)
        for term in negative_terms
        if normalize_text(str(term))
        and (
            _contains_term(normalized_title, normalize_text(str(term)))
            or _contains_term(normalized_text, normalize_text(str(term)))
        )
    )
    raw = min(
        1.0,
        len(set(positive)) * 0.14 + min(frequency, 8) * 0.035 + title_hits * 0.22,
    )
    specific_matches = {
        normalize_text(term)
        for term in positive
        if normalize_text(term) not in GENERIC_TOPIC_TERMS
    }
    if not specific_matches and len(set(positive)) < 2:
        raw = min(raw, 0.35)
    has_financial_context = any(
        _contains_term(normalized_title, anchor) or _contains_term(normalized_text, anchor)
        for anchor in FINANCE_ANCHORS
    )
    if not has_financial_context:
        raw = min(raw, 0.2)
    raw = max(0.0, raw - min(len(negative) * 0.25, 0.75))
    return round(raw, 6), tuple(dict.fromkeys(positive)), negative


def combine_topic_score(
    *,
    lexical: float,
    semantic: float | None,
    threshold: float,
    positive_matches: tuple[str, ...],
    negative_matches: tuple[str, ...],
) -> TopicScore:
    if semantic is None:
        combined = lexical
        semantic_part = "semantic unavailable"
    else:
        combined = lexical * 0.55 + semantic * 0.45
        semantic_part = f"semantic={semantic:.2f}"
    combined = round(max(0.0, min(1.0, combined)), 6)
    selected = combined >= threshold and bool(positive_matches or (semantic or 0) >= 0.55)
    explanation = (
        f"lexical={lexical:.2f}; {semantic_part}; threshold={threshold:.2f}; "
        f"positive={','.join(positive_matches) or '-'}; "
        f"negative={','.join(negative_matches) or '-'}"
    )
    return TopicScore(
        lexical_score=lexical,
        semantic_score=semantic,
        combined_score=combined,
        positive_matches=positive_matches,
        negative_matches=negative_matches,
        explanation=explanation,
        selected=selected,
    )
