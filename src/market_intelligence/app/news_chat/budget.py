"""One admission budget for existing LLM and new STT/TTS reservations."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func, or_, select
from app.config import get_settings
from app.news_chat.models import ChatGeneration


def day_start():
    return datetime.now(timezone.utc).astimezone(ZoneInfo(get_settings().timezone)).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)


async def totals(s,user_id):
    charge=func.coalesce(ChatGeneration.actual_usd,ChatGeneration.reserved_usd)
    total,own=(await s.execute(select(func.coalesce(func.sum(charge),0),
        func.coalesce(func.sum(charge).filter(ChatGeneration.user_id==user_id),0)).where(
            or_(ChatGeneration.created_at>=day_start(),ChatGeneration.status.in_(['queued','running','unknown']))))).one()
    from app.news_voice.service import charges
    v_total,v_own=await charges(s,user_id,day_start())
    return total+v_total,own+v_own
