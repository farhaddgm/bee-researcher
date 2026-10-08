"""A detected instruction requires human approval bound to current content."""
import hashlib
import json
from app.openai_client import sanitize_untrusted_source


def requires_source_review(publication, article):
    _, _, safety = sanitize_untrusted_source(title=article.title or "", text=article.normalized_text or "")
    return safety.detected or bool((publication.audit or {}).get("source_content_safety", {}).get("detected"))


def source_review_digest(publication, article):
    material = [str(publication.analysis_id), article.title, article.normalized_text,
                publication.message_text, publication.telegram_payload]
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def source_review_approved(publication, article):
    approval = (publication.audit or {}).get("source_security_approval") or {}
    return bool(approval.get("actor_id") and approval.get("at") and
                approval.get("digest") == source_review_digest(publication, article) and
                ((publication.audit or {}).get("approval") or {}).get("state") == "approved")
