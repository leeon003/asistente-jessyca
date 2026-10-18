"""scripts/guided_voice_test.py
Herramienta de prueba presencial guiada de voz y micrófono para el usuario.
Ejecuta el pipeline completo de hardware y cognición:
Microfono G435 -> Whisper STT -> JessycaBrain -> EdgeTTS -> Altavoces.
"""
import sys
import time
import os

def run_guided_test():
    print("=" * 65)
    print("  JESSYCA BRAIN 1.0 — SESIÓN GUIADA DE VALIDACIÓN DE VOZ REAL")
    print("=" * 65)
    print("Esta prueba valida el flujo completo de voz con el usuario presente:\n")
    print("  1. Detección y calibración del Micrófono (G435 / C270)")
    print("  2. Grabación de voz en vivo")
    print("  3. Transcripción con Faster-Whisper local")
    print("  4. Razonamiento con JessycaBrain y Ollama")
    print("  5. Síntesis neuronal CamilaNeural y reproducción por altavoces\n")
    
    try:
        from config.manager import get_settings
        from core.local_agent.local_agent import JessycaLocalAgent
        from core.local_agent.local_agent_models import JessycaRequest, InputModality
        from services.voice.audio_device_manager import get_audio_device_manager
        from services.voice.stt_service import get_stt_service
        from services.voice.tts_provider import get_tts_manager
        import pyaudio
        import wave
    except Exception as e:
        print(f"Error al importar dependencias de voz: {e}")
        return

    settings = get_settings()
    adm = get_audio_device_manager()
    try:
        input_dev = adm.select_device(validate_signal=True)
    except Exception as e:
        print(f"[AVISO] Fallo al seleccionar dispositivo con AudioDeviceManager: {e}")
        input_dev = None

    dev_name = getattr(input_dev, "display_name", getattr(input_dev, "name", "Predeterminado"))
    dev_idx = getattr(input_dev, "runtime_index", getattr(input_dev, "index", None))
    print(f"Dispositivo de Entrada Activo: {dev_name} (Índice temporal: {dev_idx})")
    
    confirm = input("\n¿Deseas iniciar una grabación de prueba de 4 segundos? (s/n): ").strip().lower()
    if confirm not in ("s", "si", "sí", "y", "yes"):
        print("Prueba presencial cancelada por el usuario.")
        return

    print("\n[🔴 GRABANDO... Habla ahora claramente hacia tu micrófono]")
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    RECORD_SECONDS = 4
    WAVE_OUTPUT_FILENAME = "scratch/voice_tests/live_mic_sample.wav"
    os.makedirs("scratch/voice_tests", exist_ok=True)

    p = pyaudio.PyAudio()
    dev_idx = input_dev.index if input_dev else None
    try:
        stream = p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        input_device_index=dev_idx,
                        frames_per_buffer=CHUNK)
        frames = []
        for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
        stream.stop_stream()
        stream.close()
    finally:
        p.terminate()

    print("[⏹️ GRABACIÓN FINALIZADA. Guardando muestra...]")
    wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()

    print("\n[⚙️ Transcribiendo audio con Whisper STT local...]")
    t0 = time.perf_counter()
    stt = get_stt_service()
    raw_res = stt.transcribe_file(WAVE_OUTPUT_FILENAME) if hasattr(stt, "transcribe_file") else stt.transcribe(open(WAVE_OUTPUT_FILENAME, "rb").read())
    transcript = raw_res.text if hasattr(raw_res, "text") else str(raw_res)
    stt_time = (time.perf_counter() - t0) * 1000.0
    print(f"  * Texto Reconocido: \"{transcript}\" ({stt_time:.1f} ms)")

    if not transcript or len(transcript.strip()) < 2:
        print("\n[AVISO] No se detectó voz clara en la muestra grabada.")
        print("Verifica los niveles de volumen y que el micrófono no esté silenciado físicamente.")
        return

    print("\n[🧠 Procesando instrucción con JESSYCA BRAIN...]")
    agent = JessycaLocalAgent.get_instance()
    agent.use_jessyca_brain = True
    
    t1 = time.perf_counter()
    req = JessycaRequest(
        user_input=transcript,
        modality=InputModality.VOICE,
        session_id="guided_voice_session"
    )
    res = agent.interact(req)
    brain_time = (time.perf_counter() - t1) * 1000.0
    print(f"  * Respuesta de Jessyca: \"{res.response_text}\" ({brain_time:.1f} ms)")

    print("\n[🔊 Sintetizando y reproduciendo respuesta en altavoces con CamilaNeural...]")
    tts_mgr = get_tts_manager()
    t2 = time.perf_counter()
    tts_res = tts_mgr.synthesize(res.spoken_text or res.response_text, voice_name="es-PE-CamilaNeural")
    tts_time = (time.perf_counter() - t2) * 1000.0

    audio_bytes = None
    if isinstance(tts_res, tuple) and len(tts_res) > 0:
        first = tts_res[0]
        if hasattr(first, "audio_bytes"):
            audio_bytes = first.audio_bytes
        elif isinstance(first, (bytes, bytearray)):
            audio_bytes = first
    elif hasattr(tts_res, "audio_bytes"):
        audio_bytes = tts_res.audio_bytes

    if audio_bytes:
        audio_path = "scratch/voice_tests/live_response.mp3"
        os.makedirs("scratch/voice_tests", exist_ok=True)
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(audio_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        pygame.mixer.quit()
        print(f"  * Reproducción finalizada ({tts_time:.1f} ms)")
    else:
        if hasattr(tts_mgr, "speak"):
            tts_mgr.speak(res.spoken_text or res.response_text)
            print(f"  * Reproducción directa finalizada ({tts_time:.1f} ms)")
    
    print("\n" + "=" * 65)
    print("  RESULTADOS DE LA PRUEBA PRESENCIAL:")
    print(f"  - Latencia STT: {stt_time:.1f} ms")
    print(f"  - Latencia Brain: {brain_time:.1f} ms")
    print(f"  - Latencia TTS: {tts_time:.1f} ms")
    print(f"  - Latencia E2E Total: {(stt_time + brain_time + tts_time):.1f} ms")
    print("=" * 65)

if __name__ == "__main__":
    run_guided_test()
