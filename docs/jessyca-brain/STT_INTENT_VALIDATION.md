# JESSYCA ASISTENTE 4.0 — VALIDACIÓN DE INTENCIÓN Y RESILIENCIA STT

## 1. INTRODUCCIÓN

Este documento detalla la validación empírica y los mecanismos de resiliencia introducidos en el motor semántico de **JESSYCA BRAIN 1.0** para interpretar correctamente entradas orales imperfectas capturadas desde el micrófono Logitech G435 en Windows 11.

---

## 2. MATRIZ DE RESULTADOS: PRUEBAS REALES OBLIGATORIAS (A A J)

| Caso | Entrada de Voz / Transcripción | Intención Detectada | Herramienta Ejecutada | Verificación de Seguridad | Resultado Observado | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A. Conversación** | *"Jessica, hola, ¿me escuchas?"* | `conversational` | Ninguna (Respuesta directa con LLM) | No requiere herramientas; no modifica SO | *"Sí, te escucho perfectamente. ¿En qué te puedo ayudar hoy?"* | **PASS** |
| **B. Preguntas** | *"Jessica, ¿quién fue Albert Einstein?"* | `general_query` | Ninguna (Respuesta directa con LLM) | Sin apertura de ejecutables; sin permisos elevados | Explicación histórica y científica precisa sobre Einstein y relatividad | **PASS** |
| **C. YouTube** | *"Jessica, abre YouTube y reproduce música de Mozart"* | `composite_plan:browser_youtube` | `browser.youtube` (query: "música de Mozart", op: "play") | Whitelist verificado; bloqueo de `yo.exe` | YouTube reproduce la música solicitada. Respuesta: *"Listo, abrí YouTube y reproduje música de Mozart"* | **PASS** |
| **D1. Transcripción corrupta 1** | *"Jessica, abre yo tuy y repreduce a mozar"* (Conf: 0.70) | `composite_plan:browser_youtube` | `browser.youtube` (query: "Mozart", op: "play") | Normalización fonética contextual; `yo.exe` bloqueado | Abre YouTube buscando a Mozart. Sin aplicaciones inventadas | **PASS** |
| **D2. Transcripción corrupta 2** | *"abre yu tub y pon música clásica"* (Conf: 0.75) | `composite_plan:browser_youtube` | `browser.youtube` (query: "música clásica", op: "play") | Normalización fonética contextual | Reproduce música clásica en YouTube | **PASS** |
| **D3. Transcripción corrupta 3** | *"pon videos de mozart"* (Conf: 0.85) | `action_execution:browser_youtube` | `browser.youtube` (query: "videos de mozart", op: "play") | Mapeo multimedia directo | Reproduce videos de Mozart | **PASS** |
| **D4. Incertidumbre acústica** | *"abre yo tuy y repreduce a mozar"* (Conf: 0.36) | `ambiguous / clarification_needed` | **Ninguna** (Bloqueo preventivo) | Aclaración obligatoria ante baja confianza (< 0.50) | JESSYCA pregunta: *"¿Quieres que abra YouTube y reproduzca música de Mozart?"* | **PASS** |
| **E. Orden Compuesta** | *"Jessica, baja el volumen, abre Chrome y busca información sobre Python"* | `composite_plan` (3 subtareas) | 1. `windows.audio` (bajar)<br>2. `windows.apps` (chrome)<br>3. `browser.search` (Python) | Ejecución secuencial en DAG con verificación paso a paso | Volumen disminuido al 20%, Chrome iniciado y búsqueda de Python completada | **PASS** |
| **F. Silencio / Ruido** | *Captura en silencio durante 3 ciclos* | `VoiceDiscardReason.NO_AUDIO` / `NO_VAD` | Ninguna | Bloqueo en captura; descarte total | No genera transcripción ni aprende procedimientos | **PASS** |
| **G. Frase Incompleta** | *"abre yo"* / *"abre la"* | `clarification_needed` | Ninguna | Filtro de fragmentos truncados (longitud <= 2) | Pregunta: *"¿Podrías aclararme qué aplicación deseas abrir? No entendí bien el nombre."* | **PASS** |
| **H. Memoria Contextual** | Turno 1: *"Jessica, recuerda que estamos investigando inteligencia artificial"*<br>Turno 2: *"¿Qué estábamos investigando?"* | 1. `memory_store`<br>2. `general_query` con contexto episódico | Ninguna | Almacenamiento seguro en WorkingMemory y SQLite | Recuerda y responde sobre inteligencia artificial manteniendo el contexto | **PASS** |
| **I. Verificación de Fallo** | *"Jessica, abre YouTube"* con simulación de fallo en navegador | `action_execution:browser_youtube` | `browser.youtube` (retorna `success=False`) | `ExecutionVerifier` detecta discrepancia | **Rechaza declarar éxito**. Estado: `FAILED`. No se aprende procedimiento erróneo | **PASS** |
| **J. Telemetría Real** | Interacción de voz en vivo | `conversational` | Ollama inference | Telemetría registrada | `model_inference_latency_ms` = 2,688 ms; `total_latency_ms` = 2,750 ms | **PASS** |

---

## 3. COMPARATIVA DE COMPORTAMIENTO: ANTES VS DESPUÉS

### Caso: "Jessica, abre yo tuy y repreduce a mozar"

#### Comportamiento Anterior (Defectuoso):
1. STT Whisper transcribe con baja confianza (0.36).
2. `PlannerEngine` aplica expresión regular sobre "abre yo..." y extrae `app_name = "yo"`.
3. `apps_skill.py` busca "yo" en catálogo; al no hallarlo, concatena `.exe` y genera `yo.exe`.
4. El sistema reporta éxito falso o intenta invocar un ejecutable inexistente.
5. Se almacena el turno en memoria de procedimientos con una orden errónea.

#### Comportamiento Actual (Corregido y Certificado):
1. **Normalización Fonética Contextual:**
   `ReasoningEngine._normalize_phonetic_variations()` detecta *"yo tuy"* como *"YouTube"*, *"repreduce a"* como *"reproduce"* y *"mozar"* como *"Mozart"*.
2. **Evaluación de Confianza e Incertidumbre:**
   - Si la confianza STT es >= 0.50: Se traduce directamente al tool `browser.youtube` con query `"Mozart"` y operación `"play"`.
   - Si la confianza STT es < 0.50 (como el 0.36 reportado): Se activa la puerta de seguridad de ambigüedad, respondiendo:
     *`"¿Quieres que abra YouTube y reproduzca música de Mozart?"`*
     Sin ejecutar ninguna aplicación a ciegas.
3. **Whitelist de Ejecutables en `apps_skill.py`:**
   Cualquier palabra desconocida fuera del catálogo autorizado (`apps.yaml`, Windows System Apps) es rechazada con `APP_NOT_AUTHORIZED`. Jamás se genera `yo.exe`.
4. **Protección de Procedural Memory:**
   `ProcedureLearningEngine` rechaza registrar procedimientos con confianza STT < 0.60 o con evidencias no verificadas.
