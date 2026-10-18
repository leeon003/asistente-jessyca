"""Authenticated local Aurora studio. Uses the existing core and voice services."""
from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.cancellation import CancellationToken

STATIC = Path(__file__).parent / 'studio_static'
MAX_WAV_BYTES = 4 * 1024 * 1024


class SpeechPayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PairPayload(BaseModel):
    ticket: str = Field(min_length=1, max_length=180)


def install_studio(app, auth_token: str, sessions) -> None:
    router = APIRouter(prefix='/studio')
    voice_slots = asyncio.Semaphore(2)

    def authenticate(request: Request) -> None:
        supplied = request.headers.get('authorization', '')
        if not supplied.startswith('Bearer ') or not sessions.accepts(supplied[7:]):
            raise HTTPException(401, 'Conecta Jessyca desde Ajustes con tu clave de conexión.')

    @router.get('')
    async def index():
        return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-store'})

    @router.post('/api/pair')
    async def pair(payload: PairPayload):
        session_token = sessions.redeem(payload.ticket)
        if not session_token:
            raise HTTPException(401, 'Este enlace de inicio venció. Abre Jessyca desde el escritorio otra vez.')
        from fastapi.responses import JSONResponse
        return JSONResponse({'token': session_token}, headers={'Cache-Control': 'no-store'})

    @router.get('/api/status')
    async def status(request: Request):
        authenticate(request)
        from config.manager import get_settings
        settings = get_settings()
        return {'voice': settings.VOICE_DEFAULT_VOICE, 'provider': settings.VOICE_TTS_PROVIDER,
                'stt': settings.VOICE_STT_PROVIDER, 'local_folder': r'D:\bailes de ia'}

    @router.get('/api/files')
    async def files(request: Request):
        authenticate(request)
        root = Path(r'D:\bailes de ia')
        if not root.is_dir():
            return {'folder': str(root), 'files': [], 'available': False}
        items = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() in {'.mp4', '.mkv', '.avi', '.mov', '.webm'})
        return {'folder': str(root), 'files': items[:200], 'available': True, 'count': len(items)}

    @router.post('/api/transcribe')
    async def transcribe(request: Request):
        authenticate(request)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_WAV_BYTES:
                raise HTTPException(413, 'La grabación supera el límite de un minuto.')
            data.extend(chunk)
        try:
            with wave.open(io.BytesIO(data), 'rb') as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 8000 <= wav.getframerate() <= 96000:
                    raise ValueError('Formato no admitido')
                if wav.getnframes() / wav.getframerate() > 60:
                    raise ValueError('La grabación supera un minuto')
        except (wave.Error, EOFError, ValueError) as exc:
            raise HTTPException(422, 'Se necesita audio WAV mono PCM de 16 bits, de hasta un minuto.') from exc
        from services.voice.stt_service import get_stt_service
        async with voice_slots:
            result = await asyncio.to_thread(get_stt_service().transcribe, bytes(data), timeout_seconds=15)
        return {'text': result.text, 'confidence': result.confidence, 'empty': result.is_empty}

    @router.post('/api/speech')
    async def speech(payload: SpeechPayload, request: Request):
        authenticate(request)
        from services.voice.spoken_text import prepare_spoken_text
        from services.voice.tts_provider import get_tts_manager
        token = CancellationToken()
        try:
            async with voice_slots:
                result, metrics = await asyncio.wait_for(
                    asyncio.to_thread(get_tts_manager().synthesize, prepare_spoken_text(payload.text), cancellation_token=token),
                    timeout=25,
                )
            if not result.is_success or not result.audio_bytes:
                raise HTTPException(503, 'La voz no está disponible. La respuesta escrita sigue disponible.')
            return Response(result.audio_bytes, media_type='audio/wav' if result.audio_bytes.startswith(b'RIFF') else 'audio/mpeg',
                            headers={'Cache-Control': 'no-store', 'X-Voice-Provider': metrics.provider_used})
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, 'La voz tardó demasiado. Puedes continuar por texto.') from exc
        finally:
            token.cancel()

    app.include_router(router)
    app.mount('/studio/assets', StaticFiles(directory=STATIC), name='studio-assets')
    app.mount('/studio/orb', StaticFiles(directory=Path(__file__).parents[1] / 'aurora' / 'static'), name='studio-orb')
