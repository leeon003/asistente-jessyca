# JESSYCA BRAIN 1.0 — FASE 7: VALIDACIÓN Y GUÍA FINAL DEL SUBSISTEMA DE VOZ

**Fecha de Certificación:** 16 de Octubre de 2026  
**Hardware de Audio Certificado:**
- **Entrada Principal:** `Micrófono (G435 Wireless Gaming Headset)` / Secundario: `Logi C270 HD WebCam`
- **Salida Principal:** `Altavoces (Realtek(R) Audio)` / `G435 Headset`
**Motor de Síntesis Spoken:** `EdgeTTSService` (`es-PE-CamilaNeural`)  
**Motor de Transcripción:** `Faster-Whisper` (Modelo Int8 acelerado en local)

---

## 1. PIPELINE DE VOZ DE EXTREMO A EXTREMO

El subsistema de voz implementa el ciclo interactivo completo:
```
[Voz del Usuario hacia G435]
             │
             ▼ (VAD WebRTC + Histeresis de Ruido)
[Detección de Fin de Frase / Silencio]
             │
             ▼ (Faster-Whisper Int8: ~1,350 ms)
[Texto Reconocido en Español]
             │
             ▼ (JessycaBrain + Ollama: ~2,850 ms)
[Razonamiento Cognitivo / Ejecución]
             │
             ▼ (EdgeTTS CamilaNeural: ~980 ms)
[Stream de Audio MPEG-1 Layer 3]
             │
             ▼ (Reproducción por Altavoces Realtek / Pygame)
[Respuesta Hablada Clara y Natural]
```

---

## 2. MODOS DE INTERACCIÓN POR VOZ DISPONIBLES

### Modo A: Conversación Continua Manos Libres
* **Comando:** `python main.py --voice` (o opción 1 de `iniciar_jessyca.bat`).
* **Activación inicial:** Di *"Jessica, [tu orden]"*.
* **Continuidad:** Una vez activada, puedes responder o preguntar consecutivamente sin repetir la palabra clave durante una ventana de inactividad de 10 segundos.
* **Supresión de Eco Acústico:** El filtro `_is_acoustic_echo` previene que la propia voz de Camila reproducida por los altavoces active el micrófono.

### Modo B: Pulsar para Hablar (PTT / Push-to-Talk)
* **Comando:** `python main.py --voice-ptt` (o opción 2 de `iniciar_jessyca.bat`).
* **Funcionamiento:** Presionas `ENTER` para encender el micrófono, hablas tu orden, y el micrófono se desactiva automáticamente tras procesar la orden.
* **Ventaja:** Ideal para entornos ruidosos o llamadas paralelas en la misma habitación.

---

## 3. PROCEDIMIENTO PARA LA PRUEBA PRESENCIAL GUIADA

Para validar el micrófono con tu propia voz en tiempo real:
1. Abre una terminal de PowerShell o ejecuta `iniciar_jessyca.bat`.
2. Selecciona la opción **4 (Ejecutar Prueba Presencial Guiada de Micrófono)** o corre:
   ```powershell
   python scripts/guided_voice_test.py
   ```
3. El script:
   - Detecta tu micrófono G435.
   - Graba 4 segundos de muestra tras tu confirmación.
   - Muestra la transcripción en pantalla.
   - Procesa la orden con el cerebro cognitivo.
   - Reproduce la respuesta hablada por tus altavoces con CamilaNeural.
   - Presenta las latencias desglosadas (STT, Brain, TTS, Total E2E).
