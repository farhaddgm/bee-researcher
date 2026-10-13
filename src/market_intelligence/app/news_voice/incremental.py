"""Speak stable prefixes of the existing LLM job, without a second LLM call.

Only complete sentences/lines leave the server while text is provisional.
The final asset records what was actually spoken and whether it matches the
completed canonical answer. A changed/failed answer cannot become complete.
"""
import asyncio
import hashlib
from contextlib import aclosing
import re
from app.database import SessionLocal
from app.news_chat.models import ChatGeneration
from app.news_voice import providers
from app.news_voice.storage import MAX_BYTES


class Prefix:
    def __init__(self, limit):
        self.limit = limit
        self.spoken = ''

    def advance(self, answer, final=False):
        boundary = len(answer) if final else 0
        if not final:
            for match in re.finditer(r'[.!?؟。][ \t\n]+|\n', answer):
                candidate = answer[:match.end()]
                # Incomplete markdown labels/tags must never be read aloud.
                if candidate.count('[') == candidate.count(']') and candidate.count('(') == candidate.count(')'):
                    boundary = match.end()
            if boundary==0 and len(answer)>=180:
                # A long unpunctuated sentence still starts before LLM EOF.
                for match in re.finditer(r'\s+',answer):
                    candidate=answer[:match.end()]
                    if len(candidate)>=160 and candidate.count('[')==candidate.count(']') and candidate.count('(')==candidate.count(')'):
                        boundary=match.end()
        clean = providers.spoken_text(answer[:boundary])
        if not clean.startswith(self.spoken):
            raise providers.VoiceError('voice_text_changed')
        if len(clean) > self.limit:
            raise providers.VoiceError('voice_text_too_large')
        if not final and self.spoken and len(clean)-len(self.spoken)<80:
            return ''
        part = clean[len(self.spoken):]
        self.spoken = clean
        return part


async def answer_parts(gid, limit, state):
    cursor = Prefix(limit)
    while True:
        async with SessionLocal() as session:
            generation = await session.get(ChatGeneration, gid)
            if not generation or generation.cancel_requested:
                raise providers.VoiceError('voice_audio_cancelled')
            answer, status = generation.answer, generation.status
        terminal = status not in ('queued', 'running')
        # A stopped LLM may retain draft text. Do not speak its unsent tail.
        part = cursor.advance(answer, final=status == 'completed') if not terminal or status == 'completed' else ''
        if part:
            state['spoken_text'] = cursor.spoken
            yield part
        if terminal:
            state['complete'] = status == 'completed' and cursor.spoken == providers.spoken_text(answer)
            state['original_text_hash'] = hashlib.sha256(answer.encode()).hexdigest()
            if not state['complete']:
                state['error_code'] = 'voice_answer_incomplete'
            return
        await asyncio.sleep(.1)


async def synthesize(parts, voice, language, zero_retention=False, on_chunk=None, on_contact=None):
    """Each committed prefix streams PCM immediately; bytes/timing stay bounded.

    HTTP and TTD both work with the account's verified transport. Requests are
    sequential and never retried; the original reservation covers the entire
    answer, including portions that have yet to arrive.
    """
    output = bytearray()
    timing = []
    operation = providers.http_tts if voice.transport == 'http' else providers.ttd_tts
    async with aclosing(parts) as iterator:
        async for part in iterator:
            start = len(output)
            offset = start / 32000
            async def forward(pcm):
                if len(output) + len(pcm) > min(MAX_BYTES - 44, 600 * 32000):
                    raise providers.VoiceError('audio_too_large')
                output.extend(pcm)
                if on_chunk:
                    await on_chunk(pcm)
            if on_contact:
                on_contact()
            raw, cues = await operation(part, voice, language, zero_retention, on_chunk=forward)
            if bytes(output[start:]) != raw:
                raise providers.VoiceError('voice_provider_invalid')
            timing.extend({**cue, 'start':offset + cue['start'], 'end':offset + cue['end']} for cue in cues)
    if not output:
        raise providers.VoiceError('voice_provider_empty')
    return bytes(output), timing
