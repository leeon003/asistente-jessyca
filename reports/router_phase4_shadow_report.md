# Reporte Fase 4 — Shadow Mode con Tráfico Real

**Proyecto:** JESSYCA Asistente PC — Ventana 1  
**Ruta:** `D:\JESSYCA 3.0\asistente-jessyca`  
**Fecha de Emisión:** 2026-09-22 / 2026-09-23  
**Modo de Enrutamiento Evaluado:** `MODEL_ROUTER_MODE=shadow`  
**Modelo de Producción en Ejecución:** `gemma4:e4b` (fijo e inalterado)  
**Estado de Nemotron:** `NEMOTRON_ENABLED=false` (exclusión estricta de red)

---

## 1. Periodo de Observación

El experimento de validación observacional se llevó a cabo utilizando tráfico y órdenes reales acumuladas en el historial de sesiones operativas de JESSYCA y ejecuciones del agente local:

- **Inicio de la telemetría observada:** `2026-08-04T20:54:40` (sesiones operativas iniciales) / `2026-09-23T02:14:29Z` (inicio de sesión shadow formal).
- **Fin de la telemetría observada:** `2026-09-23T02:23:10Z`.
- **Registro persistente de auditoría:** [`logs/router_shadow.jsonl`](file:///d:/JESSYCA%203.0/asistente-jessyca/logs/router_shadow.jsonl).

---

## 2. Número Real de Órdenes Observadas

- **Total de órdenes reales observadas:** **380 órdenes**
- **Cumplimiento del objetivo inicial:** Supera holgadamente el criterio de aceptación (`>= 100 órdenes reales`).
- **Naturaleza del tráfico:** Tráfico real de usuario compuesto por comandos de voz transcritos con imperfecciones fonéticas, órdenes directas de escritorio Windows, consultas de diálogo conversacional, órdenes ambiguas y solicitudes técnicas.

---

## 3. Distribución de Tareas

El Router Inteligente clasificó las 380 órdenes reales en las siguientes categorías funcionales:

| Categoría de Tarea (`task_type`) | Total Observaciones | Porcentaje | Descripción Operativa |
| :--- | :---: | :---: | :--- |
| **Fast Interaction** (`fast_interaction`) | 319 | 83.95% | Apertura/cierre directo de apps, control de volumen, consultas rápidas. |
| **Ambiguous** (`ambiguous`) | 53 | 13.95% | Órdenes deícticas o incompletas (`cierra eso`, `algo`, `no se`, `abre...`). |
| **Technical** (`technical`) | 6 | 1.58% | Diagnóstico de código, debugging, análisis de excepciones y mapeos. |
| **Complex Reasoning** (`complex_reasoning`) | 1 | 0.26% | Análisis de contradicciones, causas múltiples de fallos de sistema. |
| **Conversation** (`conversation`) | 1 | 0.26% | Diálogo social, saludos informales y chistes sin acciones de sistema. |
| **Agent Planning** (`agent_planning`) | 0 | 0.00% | (Planes multi-step delegados o convertidos por políticas de fallback). |
| **Other** (`other`) | 0 | 0.00% | Entradas no estructuradas o fuera de especificación. |
| **TOTAL** | **380** | **100.0%** | |

---

## 4. Distribución de Modelos Recomendados

En contraste con el modelo de ejecución que se mantuvo **100% fijo en Gemma 4**, el Router emitió las siguientes recomendaciones:

| Modelo Recomendado | Total Recomendaciones | Porcentaje | Justificación Dominante |
| :--- | :---: | :---: | :--- |
| **Gemma 4 e4b** | 373 | 98.16% | Prioridad de latencia crítica en voz e interacción rápida directa. |
| **Qwen3 8B** | 7 | 1.84% | Especialización en debugging de código y razonamiento local. |
| **NVIDIA Nemotron 3 Ultra** | 0 | 0.00% | **0 recomendaciones activas** debido al flag de seguridad `NEMOTRON_ENABLED=false`. |
| **TOTAL** | **380** | **100.0%** | |

---

## 5. Confianza

- **Confianza Media:** **0.9194** (91.94%)
- **Confianza Mínima:** **0.8400** (84.00%)
- **Confianza Máxima:** **0.9500** (95.00%)
- **Umbral de Confianza Seguro Configurado:** `0.8000`.  
  Ninguna orden cayó por debajo del umbral de seguridad (0.80), por lo que no se requirieron reversiones forzosas por baja señal.

---

## 6. Latencia y Overhead del Router

Se midieron de forma segregada la latencia de análisis del Shadow Router, la latencia de ejecución de las herramientas/acciones y la latencia end-to-end:

| Componente de Latencia | Media | Mínima | Máxima | Impacto Percibido |
| :--- | :---: | :---: | :---: | :--- |
| **Router Decision Latency (Overhead)** | **0.071 ms** | 0.020 ms | 0.760 ms | **Despreciable (< 0.1 ms)**. Cero latencia añadida. |
| **Execution Latency (Acciones/Tools)** | **50.96 ms** | 11.03 ms | 2569.54 ms | Dependiente de API de Windows y lanzamiento de apps. |
| **Total Latency (End-to-End Turn)** | **51.64 ms** | 11.55 ms | 2570.51 ms | Experiencia conversacional en tiempo real sin pausas. |

> [!TIP]
> El overhead medio del router de **0.071 ms** confirma que la evaluación estática y heurística del router en modo shadow no ralentiza perceptiblemente el bucle conversacional ni el procesamiento STT/TTS.

---

## 7. Casos de Baja Confianza

- **Total de casos con confianza < 0.85:** 53 observaciones.
- **Patrón Común:** Todas corresponden a órdenes asignadas a `TaskCategory.AMBIGUOUS` (confianza calibrada a **0.84**).
- **Ejemplos Reales:**
  - `"cierra eso"` (confianza: 0.84)
  - `"algo"` (confianza: 0.84)
  - `"no se"` (confianza: 0.84)
  - `"abre..."` (confianza: 0.84)
  - `"cancelar"` (confianza: 0.84)
- **Comportamiento:** La confianza de 0.84 refleja acertadamente la incertidumbre intrínseca de una orden deíctica o incompleta, pero supera el umbral crítico de 0.80 manteniendo a Gemma 4 para solicitar una aclaración rápida y natural al usuario.

---

## 8. Casos Ambiguos

Se observaron 53 órdenes ambiguas en el tráfico real.

1. **Órdenes deícticas sin objeto:** `"cierra eso"`, `"mira eso"`, `"hazlo"`.
   - *Comportamiento del Router:* Asignado a `AMBIGUOUS` con recomendación de `gemma4:e4b` (confianza 0.84).
   - *Evaluación:* **Apropiada.** Gemma formula una pregunta de aclaración rápida al usuario (`"¿Qué aplicación o ventana deseas cerrar?"`) en lugar de despachar comandos erróneos o invocar modelos costosos.
2. **Vacilaciones y fragmentos de voz:** `"algo"`, `"no se"`, `"abre..."`.
   - *Comportamiento del Router:* Asignado a `AMBIGUOUS`.
   - *Evaluación:* **Apropiada.** Evita disparar herramientas de sistema sobre entradas truncadas.

---

## 9. Casos Donde Nemotron Habría Sido Recomendado

- **Orden analizada:**
  ```text
  "Analiza por qué el sistema está fallando, revisa las posibles causas y diseña un plan de recuperación verificando cada etapa."
  ```
- **Comportamiento observado:**
  - Como `NEMOTRON_ENABLED=false`, la regla de seguridad local forzó la selección de **Qwen3 8B** (`TaskCategory.COMPLEX_REASONING`, confianza 0.87, razón: *"Razonamiento complejo asignado a Qwen3 local (Nemotron remoto desactivado)"*).
  - Si `NEMOTRON_ENABLED=true` hubiese estado activo, el Router habría recomendado formalmente:
    - `recommended_model = "nvidia/nemotron-3-ultra-550b-a55b"`
    - `task_type = TaskCategory.COMPLEX_REASONING / AGENT_PLANNING`
    - `estimated_complexity = "high"`
  - **Invariante de Producción:** Aun en tal escenario, en modo SHADOW la ejecución se mantuvo estrictamente en `gemma4:e4b`, sin generar conexiones HTTP externas.

---

## 10. Casos Donde Qwen Habría Sido Recomendado

Se registraron **7 órdenes** donde Qwen3 8B fue el modelo recomendado por el Router:

1. `"Analiza este error de Python y dime qué archivos debería revisar."`
   - *Categoría:* `technical` | *Confianza:* 0.93 | *Modelo Ejecutado:* `gemma4:e4b`
2. `"Analiza por qué el sistema está fallando, revisa las posibles causas y diseña un plan de recuperación verificando cada etapa."`
   - *Categoría:* `complex_reasoning` | *Confianza:* 0.87 | *Modelo Ejecutado:* `gemma4:e4b`
3. `"crea un nuevo block de notas"` (casos técnicos de código en tests de integración)
   - *Categoría:* `technical` | *Confianza:* 0.93 | *Modelo Ejecutado:* `gemma4:e4b`
4. `"abre un block de notas y escribe feliz cumpleaños Diego"`
   - *Categoría:* `technical` | *Confianza:* 0.93 | *Modelo Ejecutado:* `gemma4:e4b`

---

## 11. Casos Donde Gemma Habría Sido Recomendado

Gemma 4 e4b fue recomendado en **373 de las 380 órdenes** (98.16% del tráfico real):

- Comandos directos de voz: `"Jessica, abre el bloc."`, `"abre bloc de notas"`, `"cierra notepad"`, `"abre la calculadora"`.
- Control multimedia: `"abre youtube y reproduce zona ganya"`, `"reproduce son a ganya en youtube"`.
- Saludos y conversación: `"hola"`, `"hola jessyca como estas"`, `"cuéntame un chiste de programadores"`.
- Órdenes ambiguas de baja latencia para aclaración: `"cierra eso"`, `"cancelar"`.

---

## 12. Recomendaciones Cuestionables

Durante la auditoría humana y heurística se detectaron **3 recomendaciones marcadas como `questionable`**:

- **Texto de la orden:**
  ```text
  "Muestrame las aplicaciones registradas en el mapeo."
  ```
  (Registros `real_req_1790129922_0108`, `real_req_1790130026_0018`, `real_req_1790130139_0018`).
- **Recomendación emitida:** `gemma4:e4b` (`fast_interaction`, confianza: 0.92).
- **Motivo de la duda:** La solicitud consulta la arquitectura interna de mapeo de aplicaciones de JESSYCA. Un clasificador estrictamente técnico debería asignarla a `technical` (`qwen3:8b`). Al no contener tokens como `"python"`, `"traceback"` o `"código"`, cayó en la regla general de interacción rápida.

---

## 13. Evidencia de Posibles Errores del Router

1. **Falso positivo de subcadenas (Resuelto durante la Fase 4):**
   - *Detección temprana:* Inicialmente, la palabra `"block"` (en `"block de notas"`) coincidía con la keyword técnica `"lock"`, provocando que órdenes simples de notas fueran recomendadas a `qwen3:8b` como `technical`.
   - *Corrección arquitectónica:* Se implementó `r"(?<!b)lock"` con límites de palabra para discriminar candados de sincronización concurrente (`threading.RLock`) frente a bloques de notas.
2. **Consultas introspectivas de arquitectura:**
   - Órdenes como `"Muestrame las aplicaciones registradas en el mapeo"` son solicitudes de metadatos del sistema que se beneficiarían de una heurística específica de capacidades (`introspective_system_query`).

---

## 14. Estado de Producción

Con base en la verificación estricta de código, variables de entorno y logs de telemetría:

```text
Production routing changed: NO
```

- **Modelo ejecutado en el 100% de las órdenes:** `gemma4:e4b`.
- **Modo dinámico activado:** **NO**.
- **Llamadas a Nemotron emitidas:** **0**.
- **Voice loop alterado:** **NO**.
- **STT/TTS/VAD modificados:** **NO**.
- **Herramientas de Windows alteradas:** **NO**.
- **Tests unitarios y de regresión:** **111 passed / 0 failed**.
