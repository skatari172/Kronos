"""Villager voices: a line of dialogue as speech, in that villager's own voice.

Optional and presentation-only. With ELEVENLABS_API_KEY set, `POST /api/voice` returns
MP3 audio from ElevenLabs (cached on disk by voice and text, so a replay costs nothing);
without it, 503 tells the frontend to use the browser's own speech instead. The key stays
on the server. Nothing here reads or changes the world beyond a citizen's ID.
"""

import asyncio
import hashlib
import json
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api", tags=["User tools"])

# Young ElevenLabs premade voices (usable on every plan through the API), matched to
# each founder's personality.
FOUNDER_VOICES = {
    "citizen-0": "EXAVITQu4vr4xnSDxMaL",  # Elena, proud landowner: Sarah (assured)
    "citizen-1": "TX3LPaxmHKxFdv7VOQHJ",  # Marcus, ambitious baker: Liam (energetic)
    "citizen-2": "FGY2WhTYpPnrIDTdsKH5",  # Ada, sociable merchant: Laura (quirky)
    "citizen-3": "SOYHLrjzK2X1ezoPC6cr",  # Rowan, hot-headed farmhand: Harry (fierce)
    "citizen-4": "bIHbv24MWmeRgasZH58o",  # Theo, careful miller: Will (relaxed)
    "citizen-5": "cgSgspJ2msm6clMCkdW9",  # Mira, blunt builder: Jessica (bright)
    "citizen-6": "IKne3meq5aSn9XLyUdCD",  # Finn, gentle weaver: Charlie (warm)
}
# Newcomers draw one from this pool (young voices, plus River), fixed by their ID.
VOICE_POOL = [*FOUNDER_VOICES.values(), "SAz9YHcvj6GT2YYXdXww"]
# ElevenLabs speaking speed (0.7-1.2): a natural pace, just a touch brisk.
SPEED = 1.08
SETTINGS = {"stability": 0.4, "similarity_boost": 0.8, "style": 0.3, "speed": SPEED}


def voice_for(citizen_id: str) -> str:
    return (
        FOUNDER_VOICES.get(citizen_id)
        or VOICE_POOL[zlib.crc32(citizen_id.encode()) % len(VOICE_POOL)]
    )


class VoiceRequest(BaseModel):
    citizen_id: str
    text: str = Field(min_length=1, max_length=600)


def _synthesise(key: str, voice: str, text: str, model: str) -> bytes:
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps(
            {
                "text": text,
                "model_id": model,
                "voice_settings": SETTINGS,
            }
        ).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as reply:
        return reply.read()


@router.post(
    "/voice",
    summary="Speak a villager's line in their own voice (optional ElevenLabs)",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}}, 503: {"description": "Voices not configured"}},
)
async def voice(body: VoiceRequest, service: ServiceDependency):
    config = service.config
    if config.elevenlabs_api_key is None:
        raise HTTPException(503, "Voices are not configured (set ELEVENLABS_API_KEY)")
    voice_id = voice_for(body.citizen_id)
    # The settings are part of the key, so changing a voice's speed never replays old audio.
    digest = hashlib.sha256(
        f"{config.elevenlabs_model}|{voice_id}|{json.dumps(SETTINGS)}|{body.text}".encode()
    )
    cached = Path(config.voice_cache) / f"{digest.hexdigest()[:24]}.mp3"
    if cached.exists():
        return Response(cached.read_bytes(), media_type="audio/mpeg")
    try:
        audio = await asyncio.to_thread(
            _synthesise,
            config.elevenlabs_api_key.get_secret_value(),
            voice_id,
            body.text,
            config.elevenlabs_model,
        )
    except urllib.error.HTTPError as exc:
        # The service's own reason (quota, bad key) never includes the key itself.
        detail = exc.read().decode(errors="ignore")[:200]
        raise HTTPException(502, f"ElevenLabs error {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, "Could not reach ElevenLabs") from exc
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(audio)
    return Response(audio, media_type="audio/mpeg")
