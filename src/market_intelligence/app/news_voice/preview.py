"""Short-lived, bounded PCM in producer memory. No additional persisted copy.

Different app processes fall back to the completed private WAV; they never
start a second provider request. All preview access reuses asset ACL checks.
"""
import time
import uuid
from dataclasses import dataclass, field
from app.news_voice.storage import MAX_BYTES


@dataclass
class Buffer:
    chunks:list[bytes]=field(default_factory=list)
    size:int=0
    touched:float=field(default_factory=time.monotonic)
    complete:bool=False


buffers:dict[uuid.UUID,Buffer]={}


def start(aid):
    sweep()
    if len(buffers)>=4:
        # Completed previews are disposable; ready WAVs remain available.
        for key,b in list(buffers.items()):
            if b.complete:buffers.pop(key,None)
    if len(buffers)>=4:return
    buffers[aid]=Buffer()


async def append(aid,pcm):
    b=buffers.get(aid)
    if not b:return
    if not pcm or len(pcm)%2 or b.size+len(pcm)>MAX_BYTES-44:raise ValueError('invalid_preview')
    # Small frames keep cancellation and ACL checks responsive.
    for i in range(0,len(pcm),16000):b.chunks.append(bytes(pcm[i:i+16000]))
    b.size+=len(pcm);b.touched=time.monotonic()


def finish(aid):
    if aid in buffers:buffers[aid].complete=True;buffers[aid].touched=time.monotonic()


def remove(aid):buffers.pop(aid,None)


def sweep():
    for key,b in list(buffers.items()):
        if time.monotonic()-b.touched>120:buffers.pop(key,None)
