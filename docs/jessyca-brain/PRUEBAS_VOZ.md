# VALIDACIÓN DEL SUBSISTEMA DE AUDIO Y VOZ — JESSYCA BRAIN 1.0

**Proyecto:** JESSYCA Asistente Personal  
**Hardware de Prueba:** Logitech G435 Wireless Gaming Headset (Entrada) / Realtek Audio (Salida)  
**Fecha:** 16 de Octubre de 2026

---

## 1. Arquitectura del Flujo de Voz

```
  [USUARIO HABLANDO]
          │
          ▼
┌────────────────────────┐
│  Logitech G435 Headset │ (Captura PCM 16kHz Mono, búferes de 1024 frames)
└─────────┬──────────────┘
          │
          ▼
┌────────────────────────┐
│  Faster-Whisper Local  │ (STT en español, adaptación de eventos UtteranceFinal)
└─────────┬──────────────┘
          │
          ▼
┌────────────────────────┐
│   JessycaBrain Core    │ (ReasoningEngine + MemoryEngine + Ollama Local)
└─────────┬──────────────┘
          │
          ▼
┌────────────────────────┐
│ EdgeTTS (CamilaNeural) │ (Síntesis neural es-PE-CamilaNeural a MP3 / PCM)
└─────────┬──────────────┘
          │
          ▼
┌────────────────────────┐
│  Altavoces / Audífonos │ (Reproducción real mediante pygame.mixer)
└────────────────────────┘
```

---

## 2. Hardware de Audio Detectado y Verificado

Durante las pruebas en Windows 11 se identificaron los dispositivos de audio activos en el sistema:

1. **Dispositivos de Entrada (Micrófono):**
   - `Device 1: Micrófono (G435 Wireless Gaming Headset)` — 1 canal de entrada activo.
   - `Device 8: Micrófono (G435 Wireless Gaming Headset)` — Controlador secundario.
   - `Device 2: Micrófono (Logi C270 HD WebCam)` — Dispositivo auxiliar de respaldo.
2. **Dispositivos de Salida (Altavoces):**
   - `Device 4: Altavoces (Realtek(R) Audio)` — Salida estéreo predeterminada.
   - `Device 13: audífonos Diego In (G435 Wireless Gaming Headset)` — Salida inalámbrica para auriculares.

Se verificó la apertura y lectura del búfer en vivo mediante PyAudio:
```python
stream = p.open(format=paInt16, channels=1, rate=16000, input=True, input_device_index=1, frames_per_buffer=1024)
data = stream.read(1024)
# Resultado: 2048 bytes capturados con éxito por búfer sin desbordamiento.
```

---

## 3. Modos de Interacción por Voz Disponibles

### A. Modo Pulsar para Hablar (Push-To-Talk / PTT) — Opción 2 del Lanzador
- **Cómo funciona:** La consola espera a que el usuario presione la tecla `ENTER`.
- **Ventaja:** Ideal para entornos ruidosos o cuando el usuario no desea escucha continua en segundo plano. Al presionar ENTER, el micrófono se abre, graba la orden del usuario, transcribe y genera la respuesta hablada.

### B. Modo Voz Continuo — Opción 1 del Lanzador
- **Cómo funciona:** El sistema se mantiene a la escucha con VAD (Voice Activity Detection) calibrado.
- **Palabra clave de activación (Wake Word):** *"Jessica"* (o *"Jessyca"*).
- **Conversación continua:** Una vez iniciada la conversación, el usuario puede continuar hablando sin repetir el wake word durante la ventana de diálogo activo.
- **Protección contra Eco Acústico:** `_is_acoustic_echo` compara la orden capturada con las últimas palabras emitidas por el asistente. Si el micrófono captura el audio emitido por los altavoces, lo descarta automáticamente para evitar bucles infinitos.

### C. Sesión Guiada de Validación Presencial — Opción 4 del Lanzador
- Ejecutable mediante: `python scripts/guided_voice_test.py` o seleccionando `4` en el menú principal.
- Flujo guiado paso a paso:
  1. Detecta y calibra el micrófono Logitech G435.
  2. Graba una muestra de 4 segundos del usuario.
  3. Muestra la transcripción obtenida en pantalla.
  4. Envía la transcripción a `JessycaBrain` para su procesamiento.
  5. Sintetiza la respuesta con `es-PE-CamilaNeural` y la reproduce en los altavoces.
  6. Presenta un desglose métrico de latencia (STT + LLM + TTS = Latencia Total).

---

## 4. Pruebas de Resiliencia y Manejo de Errores

1. **Silencio Prolongado:** Si el micrófono no detecta audio durante varios turnos, la sesión pasa a reposo (`IDLE`) sin bloquear el sistema.
2. **Desconexión o Fallo de Audio:** Si el dispositivo de audio presenta un fallo transitorio, `VoiceDeviceResolver` intenta reconectar con el dispositivo predeterminado de Windows sin abortar el proceso principal.
3. **Parada de Emergencia Hablada:** Pronunciar *"Detente"*, *"Para"* o *"Cancela"* activa `EmergencyStopManager`, abortando la reproducción de voz y cualquier plan de herramientas activo de forma instantánea.
