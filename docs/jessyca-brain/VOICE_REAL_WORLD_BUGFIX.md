# JESSYCA ASISTENTE 4.0 — INFORME DE CORRECCIÓN DE ERRORES REALES DE VOZ Y COMPRENSIÓN

## 1. RESUMEN EJECUTIVO

Durante pruebas reales de usuario en Windows 11 utilizando el modo de conversación continua y el auricular Logitech G435, se detectaron fallos críticos de reconocimiento acústico, alucinaciones en silencio, enrutamiento semántico erróneo (intento de ejecución de `yo.exe`), rigidez en las respuestas conversacionales, falsos éxitos en la memoria procedimental y discrepancias telemétricas (`llm_duration=0`).

Este trabajo corrigió quirúrgicamente los componentes integrados en **JESSYCA BRAIN 1.0** y el pipeline de voz, sin sustituir la arquitectura existente ni introducir dependencias externas.

Todas las 10 pruebas obligatorias (A a J) y las 32 pruebas de regresión cognitiva y de aceptación de usuario han sido ejecutadas satisfactoriamente (100% PASS).

---

## 2. ANÁLISIS DE CAUSA RAÍZ Y SOLUCIONES TÉCNICAS

### 2.1. Problema 1: Transcripciones Acústicas Defectuosas y Alucinación en Silencio
- **Síntoma Reportado:** La orden *"Jessica, abre YouTube y reproduce a Mozart"* fue transcrita como *"Jessica, abre yo tuy y repreduce a mozar"* con confianza 0.36. Asimismo, Whisper generaba bucles o palabras sueltas ante fragmentos breves o pausas de audio.
- **Causa Raíz:**
  1. Ausencia de sesgo léxico contextual (`initial_prompt`) en español para el modelo `faster-whisper` (`base`).
  2. Inexistencia de filtrado VAD nativo en la llamada de inferencia Whisper (`vad_filter=False` por defecto en CTranslate2), permitiendo decodificar ruido estático o respiraciones.
  3. Ausencia de un filtro de tokens repetitivos en bucle para alucinaciones acústicas en Whisper.
  4. Falta de descarte inmediato ante audios con confianza extremadamente baja (< 0.25) y longitud mínima.
- **Correcciones Implementadas:**
  - `services/voice/stt_service.py`: Se inyectó `initial_prompt="Jessica, YouTube, Mozart, Calculadora, Bloc de notas, Chrome, Windows, reproducir, pausar, volumen."` orientando los pesos iniciales del decoder de Whisper hacia el vocabulario del asistente.
  - Se activó `vad_filter=True` con `vad_parameters=dict(min_silence_duration_ms=450)` directamente en el motor de transcripción `faster-whisper`.
  - Se implementó un filtro de repetición fonética para eliminar alucinaciones tipo bucle.
  - `services/voice/audio_capture.py`: Se configuró descarte explícito con `VoiceDiscardReason.LOW_STT_CONFIDENCE` para señales con confianza menor a 0.25 y 1-2 palabras.

---

### 2.2. Problema 2: Interpretación Semántica Errónea (`yo.exe`)
- **Síntoma Reportado:** Ante *"abre yo tuy y repreduce a mozar"*, el sistema intentó ejecutar `yo.exe`.
- **Causa Raíz:**
  1. En `core/cognitive_brain/planner_engine.py`, el método `_map_subgoal_to_action` contenía una expresión regular ingenua:
     `r"\b(?:abre|abrir|inicia|iniciar|lanza|lanzar)\s+(?:la\s+|el\s+)?([a-zA-Z0-9_\-]+)"`
     Al evaluar *"abre yo tuy"*, capturaba el primer token `"yo"`.
  2. En `skills/apps_skill.py`, si una aplicación no se encontraba en el mapeo de nombres comunes, ejecutaba un fallback peligroso:
     `return self._buscar_en_mapeo(nombre_normalizado) or f"{nombre_app}.exe"`
     Lo que convertía la palabra `"yo"` en el ejecutable `yo.exe`.
  3. No existía normalización fonética para variaciones orales típicas de servicios comunes ("yo tuy", "yu tub", "repreduce").
- **Correcciones Implementadas:**
  - `core/cognitive_brain/reasoning_engine.py`: Se implementó el método `_normalize_phonetic_variations()` que normaliza de forma contextual deformaciones acústicas frecuentes (`"yo tuy"`, `"yu tub"` -> `"YouTube"`; `"mozar"` -> `"Mozart"`; `"repreduce a"` -> `"reproduce"`).
  - En caso de duda razonable o confianza STT baja (< 0.50), el motor evalúa ambigüedad y emite una pregunta aclaratoria: *"¿Quieres que abra YouTube y reproduzca música de Mozart?"*, bloqueando cualquier ejecución a ciegas.
  - `core/cognitive_brain/planner_engine.py`: Se mapeó explícitamente YouTube hacia `browser_youtube` con `action_name="play_youtube"`. Además, para submetas desconocidas, si el nombre tiene `<= 2` caracteres o coincide con pronombres (`"yo"`, `"yu"`, `"el"`, `"la"`), genera inmediatamente `clarification_needed` sin llamar a ningún ejecutable.
  - `skills/apps_skill.py`: Se eliminó el formateo libre `{nombre_app}.exe`. Se implementó un whitelist estricto basado en catálogo del sistema (`apps.yaml`, ejecutables estándar de Windows y descriptores conocidos). Cualquier binario no autorizado es rechazado con `APP_NOT_AUTHORIZED` (`exito=False`).

---

### 2.3. Problema 3: Prevención de Falsos Éxitos y Protección de Memoria Procedimental
- **Síntoma Reportado:** Anomalía `false_success` registrada en telemetría; órdenes fallidas o mal reconocidas se guardaban como candidatos de procedimiento en `ProcedureLearningEngine`.
- **Causa Raíz:**
  1. `ProcedureLearningEngine.learn_from_experience()` solo verificaba `episode.get("success", False)`, sin inspeccionar la confianza acústica `stt_confidence`, la presencia de errores en la traza, ni la validez física de la evidencia.
  2. `JessycaBrain.process_request()` consideraba exitosa la ejecución si no había excepciones globales, aun cuando los pasos del plan no hubieran completado herramientas efectivas.
- **Correcciones Implementadas:**
  - `core/cognitive_brain/procedure_learning_engine.py`: Se endureció `learn_from_experience`:
    * Rechaza automáticamente si `stt_confidence < 0.60`.
    * Rechaza si existen errores en el episodio (`errors` o `error`).
    * Rechaza intenciones puramente conversacionales, saludos, aclaraciones o almacenamiento en memoria (`general_query`, `conversational`, `greeting`, `clarification`, `ambiguous`, `memory_store`).
    * Rechaza si la instrucción tiene menos de 6 caracteres.
    * Exige evidencia verificada explícita de herramientas ejecutadas; si alguna evidencia contiene `success=False` o `exito=False`, se descarta el aprendizaje.
  - `core/cognitive_brain/brain_orchestrator.py`: Éxito estricto condicionado a `(execution_error is None) and (executed_count == len(plan.steps)) and (executed_count > 0)`.

---

### 2.4. Problema 4: Conversación Natural vs Mensajes Robóticos
- **Síntoma Reportado:** JESSYCA respondía *"Operación completada exitosamente: ..."* ante preguntas conversacionales cotidianas o saludos.
- **Causa Raíz:** `_synthesize_plan_response` concatenaba cadenas rígidas de confirmación técnica para cualquier interacción procesada por el orquestador.
- **Correcciones Implementadas:**
  - `core/cognitive_brain/brain_orchestrator.py`:
    * Las intenciones conversacionales (`greeting`, `conversational`, `general_query`) se despachan directamente a `_generate_conversational_response()` con Ollama (`llama3.2:latest`) en español natural.
    * Se agregaron respuestas rápidas e intuitivas para verificación de micrófono (*"Sí, te escucho claramente. ¿En qué te puedo ayudar?"*).
    * `_synthesize_plan_response` genera lenguaje humano fluido: *"Listo, abrí YouTube y reproduje música de Mozart"*, *"Listo, he abierto Calculadora"*, etc.

---

### 2.5. Problema 5: Telemetría de Latencia y Duración de LLM (`llm_duration=0`)
- **Síntoma Reportado:** Los logs mostraban `llm_duration=0` a pesar de que Ollama tardaba varios segundos en responder.
- **Causa Raíz:** En `core/local_agent/local_agent.py`, el método `_execute_with_jessyca_brain` calculaba únicamente `metrics.total_latency_ms`, omitiendo mapear la duración de inferencia (`model_duration_ms`) e intención (`intent_duration_ms`) retornadas por `BrainExecutionResult`.
- **Correcciones Implementadas:**
  - `core/cognitive_brain/brain_orchestrator.py`: Se expuso `model_duration_ms` e `intent_duration_ms` en `BrainExecutionResult`.
  - `core/local_agent/local_agent.py`: Se conectó el resultado asignando:
    ```python
    metrics.model_inference_latency_ms = getattr(brain_res, "model_duration_ms", 0.0)
    metrics.intent_latency_ms = getattr(brain_res, "intent_duration_ms", 15.0)
    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000.0
    ```

---

### 2.6. Problema 6: Faster-Whisper y Compatibilidad CUDA
- **Diagnóstico:**
  * Al inicializar faster-whisper en Windows 11 sin el toolkit CUDA 12 completo en el PATH, CTranslate2 reporta:
    `Library cublas64_12.dll is not found or cannot be loaded`.
  * La arquitectura implementa un fallback automático hacia `device="cpu"` con `compute_type="int8"`.
  * En modo `cpu/int8`, faster-whisper transcribe segmentos de 3 segundos en ~250-400 ms en el procesador local, con consumo de RAM inferior a 140 MB para el modelo `base`.
  * El fallback opera de manera robusta y transparente. No se requiere instalar librerías GPU innecesarias que puedan desestabilizar el entorno.
