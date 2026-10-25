# Auditoría conversacional de JESSYCA Asistente

Fecha: 24 de octubre de 2026. Repositorio: `leeon003/asistente-jessyca`. Base de revisión: `3c41be2df5411fe59f603aa80a0f09e862354b3c`. Rama: `codex/conversational-fluency`.

## Alcance y evidencia

Este trabajo ofrece un inventario estático de todos los archivos Python rastreados y una revisión funcional focalizada del recorrido conversacional. El inventario inicial abarcó 1.111 archivos y aproximadamente 208.000 líneas, sin errores de sintaxis. El JSON de inventario se genera con `python scripts/audit_conversation_inventory.py` e incluye rutas, líneas e importaciones; CI lo publica como artefacto y no se versiona para evitar un diff de miles de líneas; incorpora los archivos nuevos una vez rastreados. Un inventario no demuestra corrección semántica ni obsolescencia. No se presenta como revisión humana completa de cada línea del repositorio ni como certificación de producción.

Se inspeccionaron los puntos de entrada de consola y web, el agente local, el manejador conversacional, captura/VAD, STT, TTS, control de interrupciones, sesiones, contexto, recuperación de memoria, planificadores y sus barreras de ejecución. Se ejecutaron pruebas focalizadas; no se revalidaron todas las miles de pruebas históricas. No se borró ningún módulo.

## Recorrido observado

| Área | Implementación revisada | Conclusión |
|---|---|---|
| Consola | `interfaces/modo_voz.py` | Captura calibrada → Google STT → agente → TTSManager. El ciclo habitual espera toda la respuesta; el modo nuevo permite hablar por frases. La captura continúa siendo secuencial. |
| Entrada local de voz | `core/local_agent/voice_interface.py` | Tiene una ruta independiente con proveedores inyectables. Sus valores por defecto son sintéticos/mock: no confundir pruebas de esta interfaz con micrófono real. |
| Pipeline alternativo | `services/voice/voice_pipeline.py` | Otro orquestador con wake/VAD/STT/agent/TTS. No hay evidencia suficiente para eliminarlo ni para afirmar que comparte todas las garantías de la consola. |
| Captura | `services/voice/audio_capture.py`, `audio_device_manager.py`, `device_resolver.py` | Captura real usa SpeechRecognition, pre/post-roll, VAD e histéresis. El silencio adaptativo de 1–1,35 s puede dominar la percepción de demora. No se reduce sin corpus de voz y ruido. |
| Abstracción de micrófono | `services/voice/audio_input.py` | `MicrophoneAudioSource.read_chunk` devuelve silencio; es un placeholder, no un backend real. La consola usa otro motor. |
| STT | `services/voice/stt_service.py`, `audio_capture.py` | La consola llama Google; `confidence=0.90` es un valor fijo, no precisión medida ni WER. No se usa como prueba de calidad. |
| Conversación | `core/local_agent/conversational_handler.py` | El prompt ya solicita 2–3 frases breves. Streaming real con Ollama; respaldo contextual cuando no hay inferencia. No hace falta copiar un prompt propietario. |
| Memoria | `conversation_context.py`, `conversation_models.py`, `core/memory_retriever.py`, `core/memory/memory_policy.py` | Sesiones separadas, historial reciente (8 turnos, presupuesto aproximado 3.500 caracteres) y memorias con políticas propias. Una sola pareja de turnos puede superar el presupuesto actual; queda pendiente un límite estricto que preserve entidades. Memoria no equivale a autorización. |
| Planificación | `core/planning`, `core/tool_planner`, `core/are/runtime.py`, `core/jde/runtime_binding.py` | Hay varias capas con contratos distintos. ARE propone/descompone; JDE y las barreras existentes gobiernan ejecución. La conversación puede emitir texto temprano; una acción mantiene la ruta de ejecución y verificación antes de anunciar resultados. |
| Transporte | `interfaces/webui_bridge/app.py`, `adapter.py` | El generador síncrono corre en un trabajador; la adaptación SSE necesita control de presión, cancelación y error explícito. |
| TTS | `services/voice/tts_provider.py`, `tts_service.py`, `VoiceSpeaker` | TTSManager admite cancelación y proveedores/fallback. `EdgeTTSService.speak` sintetiza pero no demuestra reproducción física. Los fallbacks SAPI/pyttsx3 requieren validación propia de interrupciones. |

## Fallos corregidos y pruebas que los reproducen

1. La entrada de voz interpretaba subcadenas como “para” en “comparar”/“prepara” como cancelaciones. Ahora reconoce comandos completos normalizados. Las frases vacías o “por favor” tampoco son interrupciones puras.
2. La interfaz local tenía un controlador distinto del gestor de turnos y no pasaba el token a `speak`. Comparten controlador y cancelación; una interrupción durante síntesis ya no se anuncia como éxito. `process_voice` conserva el identificador de sesión al sintetizar.
3. Streaming conversacional omitía el bloqueo inicial de emergencia y no registraba tokens activos. Se comprueba emergencia/cancelación, se registran y limpian los tokens, y una respuesta cancelada no se guarda como turno completo.
4. Un fallo del proveedor tras emitir texto podía concatenar una respuesta de respaldo ajena. Ahora se propaga el fallo parcial; SSE emite un error explícito sin `finish_reason=stop` y sin filtrar detalles internos.
5. La adaptación SSE tenía cola sin límite, silenciaba excepciones y seguía produciendo tras desconexión. Usa una cola de 16 entradas y cancelación cooperativa, con cierre del iterador en su hilo propietario. Ollama cierra la respuesta HTTP al cerrar el generador.
6. La consola podía repetir mediante SAPI una respuesta cancelada en TTSManager. Propaga el token y evita ese fallback tras cancelación.
7. El timeout de sesión podía expirar durante procesamiento/reproducción y `followup_timeout` no se aplicaba. Esas fases ya no se tratan como silencio; el seguimiento usa el menor límite entre idle y followup.

Las pruebas nuevas están en `tests/fluency/test_conversational_fluency.py`. Cubren emisión temprana, tamaño máximo de frase, interrupción concurrente, fallo TTS, emergencia, memoria tras cancelación, error parcial, desconexión y liberación HTTP. Las suites de memoria y planificación se ejecutan para comprobar sus contratos existentes, no para atribuirles capacidades nuevas.

## Emisión de voz por frases

`services/voice/streaming.py` acumula texto hasta puntuación o hasta 180 caracteres y pide TTS antes de agotar el generador. Conserva presión síncrona: no introduce una cola ilimitada de voz. Un fallo TTS o cancelación impide consumir más respuesta. No recorta silenciosamente la respuesta final ni modifica confirmaciones de acciones.

Activación experimental desde PowerShell, en la raíz del repositorio:

```powershell
$env:JESSYCA_VOICE_STREAMING = 'true'
python -m interfaces.modo_voz
```

Volver al flujo habitual:

```powershell
Remove-Item Env:JESSYCA_VOICE_STREAMING -ErrorAction SilentlyContinue
```

La opción se consulta desde el entorno del proceso. La entrada en `.env.example` es documentación; este módulo no añade un cargador nuevo de `.env`. Para una prueba real hacen falta las dependencias de audio del proyecto, un dispositivo y proveedores disponibles; el entorno mínimo de CI usa mocks.

## Instrumentación y límites de las mediciones

- `[CONVERSATION_STREAM_LATENCY]`: petición correlacionada, primer texto, tiempo total e interrupción. `first_text_latency_ms=null` significa que no hubo texto.
- `[STREAM_LATENCY]`: primer token entregado al consumidor SSE y duración del generador, correlacionados por completion ID.
- `[VOICE_STREAM_LATENCY]`: primer texto, primera solicitud TTS, frases reproducidas con éxito informado por el proveedor, tiempo total y cancelación.
- Se mantienen las métricas de STT, planificación, inferencia y barge-in existentes. No se presentan los valores fijos o estimados históricos como mediciones nuevas.

La prueba de reloj simulado demuestra primera solicitud TTS a 100 ms y final de texto a 300 ms para tres fragmentos espaciados artificialmente. Es evidencia de emisión incremental, no un benchmark de hardware ni una mejora porcentual frente a Perplexity. No se midieron latencias reales de micrófono, GPU, red o altavoz.

Para evaluar producción: recopilar p50/p95 de EOS→STT final, STT→primer texto, EOS→primer audio real y habla del usuario→silencio del altavoz; separar modelo frío/caliente, proveedor, dispositivo, idioma, longitud y ruido. Presupuesto sugerido para evaluar, aún no certificado: primer audio p95 <1,5 s e interrupción p95 <250 ms. No reducir seguridad para cumplirlos.

## REA y Perplexity: investigación pública

La interpretación más probable de “Rea” es **Reverse Engineer Anything**. La web de REA describe análisis de aplicaciones, JavaScript, binarios y observaciones de navegador. El changelog oficial de Perplexity del 19 de octubre de 2026 cita REA para su función Reverse Engineer. Eso identifica la herramienta probable; no concede acceso al backend, pesos, secretos o código privado de Perplexity.

Se consultaron documentación pública y condiciones oficiales; no se instaló REA, no se decompiló Perplexity, no se inspeccionaron sesiones privadas ni se eludieron protecciones. REA no aporta ventaja necesaria para analizar el Python que el propietario ya autorizó a revisar. Para comparar la experiencia basta diseñar una implementación propia y pruebas de comportamiento público permitido.

Las condiciones de Perplexity consultadas restringen ingeniería inversa y ciertos usos automatizados, con excepciones según autorización y ley aplicable. No se deduce autorización de tener una cuenta o de que la página sea pública. Este trabajo se limita a documentación pública. Cualquier futura observación interactiva debe verificar las condiciones de la modalidad concreta; las API tienen condiciones distintas. No se emite una conclusión jurídica universal.

La documentación pública de la API describe deltas de texto progresivos. Ese comportamiento inspira el requisito funcional de mostrar respuesta temprana; el código del PR se escribió sobre JESSYCA y las bibliotecas existentes, sin copiar implementación propietaria ni afirmar conocer la arquitectura interna de Perplexity. No se ha comparado empíricamente su voz con JESSYCA.

Fuentes consultadas el 24 de octubre de 2026:

- [REA: funcionamiento](https://rea.tools/)
- [REA: FAQ y capacidades](https://rea.tools/faq/)
- [Perplexity: changelog con REA](https://www.perplexity.ai/changelog/ultrafast-computer-models-decisions-api-and-connector-controls)
- [Perplexity: streaming documentado](https://docs.perplexity.ai/docs/agent-api/output-control)
- [Perplexity: condiciones oficiales, versión francesa accesible](https://www.perplexity.ai/fr/hub/legal/terms-of-service)

## Trabajo pendiente antes de equivalencia conversacional

**Prioridad alta:** la consola no captura audio mientras reproduce TTS. El controlador sabe interrumpir si recibe chunks, pero no existe aquí un alimentador continuo de micrófono durante la salida. Hace falta un único propietario del dispositivo, buffer de pre-roll del habla interruptora, supresión de eco probada, cancelación y entrega del nuevo turno sin perder sílabas. Este PR no certifica barge-in acústico de extremo a extremo. Las pruebas concurrentes verifican el contrato software.

**Prioridad alta:** una lectura HTTP bloqueada sólo responde a cancelación cuando devuelve datos o vence su timeout (hasta 30 s en la ruta conversacional actual). La cola y el audio dejan de consumir, pero eso no demuestra interrupción inmediata de inferencia remota. Considerar transporte con cancelación nativa y pruebas con servidor lento.

**Prioridad media:** consolidar las rutas de voz con pruebas de equivalencia; conectar claramente memoria de sesión y largo plazo sin multiplicar recuperaciones; acotar estrictamente historial; medir coste de sondeo de disponibilidad Ollama (timeout 3,5 s), arranque de modelos y proveedores. No cambiar enrutamiento experimental sin un conjunto de evaluación.

**Prioridad media:** la sesión sigue usando reloj de pared y los callbacks antiguos no tienen generación de turno; probar cambios del reloj y finalizaciones tardías antes de introducir full duplex. SAPI/pyttsx3 siguen requiriendo pruebas de corte físico. Una frase larga sin puntuación se divide por tamaño; abreviaturas y decimales necesitan segmentación más fina antes de activar por defecto.

Para retirar módulos se exige: referencias estáticas, trazas de ejecución representativas, consumidores y configuración conocidos, prueba de equivalencia, migración y reversión. La ausencia de importación estática sola no demuestra obsolescencia.

## Validación reproducible

El workflow `.github/workflows/conversational-fluency.yml` configura Windows y Ubuntu con Python 3.11/3.12 y publica JUnit. La verificación local se realizó en Windows con Python 3.11.9, incluyendo un entorno virtual limpio. El estado de GitHub Actions debe comprobarse en el PR; configurar la matriz no equivale a haberla pasado.

```powershell
python -m pytest tests/interfaces/webui_bridge tests/fluency tests/voice/test_natural_turn_taking_phase52.py tests/voice/test_continuous_voice_session_phase51.py tests/core/llm/test_inference_provider.py tests/agent/test_memory_retriever.py tests/planning/test_planning_engine.py tests/autonomy/test_memory_cannot_grant_authority.py
```

La batería local ampliada añade todas las pruebas de `tests/voice` y `tests/conversation`. Resultado final local: **283 pruebas aprobadas en 69,59 s** en Windows/Python 3.11.9. La matriz focalizada también pasó en un entorno virtual Windows limpio: **95 pruebas aprobadas** (dos avisos de deprecación de Starlette). No se probaron dispositivos físicos ni se ejecutó la suite global. La revisión queda en borrador mientras falten la escucha simultánea y los benchmarks físicos; no se anuncia equivalencia con Perplexity.
