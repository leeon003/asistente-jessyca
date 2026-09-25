# REPORTE DE FASE 3 — ROUTER INTELIGENTE EXPERIMENTAL

**Proyecto:** JESSYCA Asistente PC — Ventana 1  
**Ruta:** `D:\JESSYCA 3.0\asistente-jessyca`  
**Fecha:** 22 de Septiembre de 2026  
**Modelos Evaluados:**
- **Gemma 4 e4b:** Modelo local principal (muy baja latencia, <400 ms, interacción rápida de voz y diálogo directo).
- **Qwen3 8B:** Modelo local técnico (latencia media ~750 ms, análisis de código, debugging, trazas y offline fallback).
- **NVIDIA Nemotron 3 Ultra (550B):** Provider remoto experimental (`nvidia/nemotron-3-ultra-550b-a55b`, alta latencia ~1766 ms, planificación multi-step compleja, desactivado por defecto).

---

## 1. RESUMEN EJECUTIVO Y ESTADO DE PROTECCIÓN

Se completó con éxito la implementación y evaluación experimental del **Router Inteligente Multi-Modelo** de JESSYCA PC, operando bajo las salvaguardas arquitectónicas requeridas:

| Invariante de Seguridad | Estado | Evidencia |
| :--- | :---: | :--- |
| **Routing Dinámico en Producción** | **DESACTIVADO** | `MODEL_ROUTER_MODE=static` por defecto en configuración. |
| **Modelo Principal del Sistema** | **INALTERADO** | `gemma4:e4b` permanece como modelo por defecto indiscutible. |
| **Flag de Nemotron Remoto** | **PROTEGIDO** | `NEMOTRON_ENABLED=false` por defecto en `.env` y settings. |
| **VRAM Local (RTX 3060 12GB)** | **PRESERVADA** | `vram_estimate_mb=0` para Nemotron remoto; VRAM 100% para modelos locales. |
| **Pipeline de Ejecución y Verificación** | **PRESERVADO** | El router únicamente clasifica y recomienda; **NO ejecuta acciones**, **NO declara éxito** y **NO sustituye al verificador**. |
| **Subsistema de Voz y Audio** | **INALTERADO** | Cero modificaciones en STT, TTS, VAD, Wake Word ni bucle principal de voz. |
| **JESSYCA Mobile (Ventana 2)** | **INALTERADO** | Aislamiento total garantizado. |

---

## 2. ARQUITECTURA DEL ROUTER

El router se implementó como un desacoplador de decisiones de inferencia que opera antes del envío al modelo, manteniendo el flujo auditado:

```text
                    USUARIO / ORQUESTADOR
                               │
                               ▼
                   ROUTER EXPERIMENTAL (Fase 3)
                   (Sub-millisecond: ~0.47 ms)
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
          GEMMA               QWEN             NEMOTRON
      rápido (<400ms)    técnico (~750ms)    complejo (~1.7s)
            │                  │                  │
            └──────────────────┼──────────────────┘
                               ▼
                        MODELO ELEGIDO
                               │
                               ▼
                        PLAN / RESPUESTA
                               │
                               ▼
                       EJECUTOR DE ACCIONES
                               │
                               ▼
                      VERIFICADOR FORMAL
                               │
                               ▼
                      RESULTADO VERIFICADO
```

### Principio de Clasificación Contextual y Heurística Multi-Dimensional
El router no utiliza reglas simplistas ("complejo=Nemotron, simple=Gemma"). Evalúa contextualmente:
1. **Prioridad de Voz / Latencia Crítica:** Si el comando proviene del canal de voz o inicia con vocativos de interacción rápida, prioriza estrictamente a `gemma4:e4b` (<400 ms), evitando pagar penalizaciones remotas de ~1.7s en órdenes cotidianas ("Abre el bloc", "¿Qué hora es?").
2. **Naturaleza Técnica y Código:** Errores de Python, tracebacks, condiciones de carrera y análisis de sintaxis son dirigidos a `qwen3:8b` como especialista local.
3. **Planificación Multi-Step y Razonamiento Deductivo:** Tareas con múltiples etapas interdependientes (`AGENT_PLANNING`), contradicciones lógicas o cálculo de trade-offs (`COMPLEX_REASONING`) son candidatas a `Nemotron 3 Ultra` **únicamente si** `NEMOTRON_ENABLED=true` y existe conectividad de red.
4. **Restricción Offline:** Si no hay internet (`INTERNET_AVAILABLE=false`), Nemotron queda estrictamente excluido y la carga compleja se redirige a `qwen3:8b` y `gemma4:e4b`.
5. **Umbral de Confianza:** Si la confianza calculada es menor al umbral configurable (`0.80`), el router revierte automáticamente a `gemma4:e4b` como modelo seguro.

---

## 3. MODOS DE OPERACIÓN IMPLEMENTADOS

El router soporta tres modos estrictos gobernados por la variable `MODEL_ROUTER_MODE`:

### 1. Modo `STATIC` (Por defecto de producción)
- **Comportamiento:** No realiza ninguna alteración ni introduce bifurcaciones dinámicas.
- **Modelo de Ejecución:** Siempre devuelve el `current_model` configurado (`gemma4:e4b`).
- **Logs:** Operación silenciosa estándar.

### 2. Modo `SHADOW` (Modo central de Fase 3)
- **Comportamiento:** Analiza la solicitud, calcula la categoría, la confianza, el modelo recomendado y la razón, y registra un evento estructurado en formato JSONL en `logs/router_shadow.jsonl`.
- **Modelo de Ejecución:** La inferencia real **continúa utilizando el modelo actual** (`gemma4:e4b`). No altera en lo absoluto el comportamiento del asistente.
- **Estructura de Log Shadow Registrada:**
  ```json
  {
    "timestamp": 1758564700.12,
    "iso_time": "2026-09-22T19:12:47.781Z",
    "request_id": "req_shadow_01",
    "router_mode": "shadow",
    "user_text": "Planifica cómo solucionar este error de arquitectura y valida cada etapa",
    "current_model": "gemma4:e4b",
    "recommended_model": "nvidia/nemotron-3-ultra-550b-a55b",
    "confidence": 0.91,
    "task_type": "agent_planning",
    "complexity": "high",
    "reason": "Planificación multi-step y separación formal REASONING->PLAN asignada a Nemotron 3 Ultra.",
    "nemotron_available": true,
    "execution_model": "gemma4:e4b",
    "latency_ms": 0.45,
    "verification_result": "SHADOW_RECORDED"
  }
  ```

### 3. Modo `EXPERIMENTAL` (Habilitado sólo en entornos de benchmark y pruebas)
- **Comportamiento:** Selecciona dinámicamente el modelo recomendado si cumple con todas las restricciones de disponibilidad y umbrales de confianza.
- **Mecanismo de Activación:** Requiere flag explícito de configuración o inyección directa en entornos de prueba controlados.

---

## 4. SUITE DE BENCHMARK Y CASOS DE PRUEBA (50 CASOS)

Se diseñó y ejecutó una suite exhaustiva de 50 casos en `tests/router/test_cases.py` con la siguiente distribución:

| Categoría | Casos | Tipo de Tarea | Modelo Esperado / Aceptable | Confianza Mín. |
| :--- | :---: | :--- | :--- | :---: |
| **Fast Interaction** | 10 | Saludos, consultas de reloj, comandos directos de Windows por voz. | `gemma4:e4b` | 0.85 |
| **Technical** | 10 | Tracebacks, KeyError, race conditions, memory leaks, descriptores. | `qwen3:8b` (o Nemotron) | 0.85 |
| **Complex Reasoning**| 10 | Coherencia lógica, trade-offs, paradoja de Bayes, contradicciones. | `nemotron-3-ultra` (o Qwen) | 0.85 |
| **Agent Planning** | 10 | Planes de 5 pasos, copia+hash, reorganización atómica, rollback. | `nemotron-3-ultra` (o Qwen) | 0.85 |
| **Offline** | 5 | Tareas complejas o simples en entornos sin conexión a internet. | `qwen3:8b` / `gemma4:e4b` | 0.80 |
| **Ambiguous** | 5 | Deícticos e instrucciones incompletas ("cierra eso", "hazlo"). | `gemma4:e4b` | 0.80 |
| **TOTAL** | **50** | Cobertura integral multi-dominio | — | — |

---

## 5. RESULTADOS CUANTITATIVOS DEL BENCHMARK

La evaluación estadística automatizada ejecutada con `python tests/router/run_router_benchmark.py` arrojó los siguientes resultados:

| Métrica Evaluada | Resultado Obtenido | Meta / Tolerancia | Estado |
| :--- | :---: | :---: | :---: |
| **Total de Casos Evaluados** | **50** | Mínimo 50 | CUMPLIDO |
| **Routing Accuracy Global** | **100.0%** | >= 90.0% | EXCELENTE |
| **Falsos Enrutamientos (False Routings)** | **0 (0.0%)** | <= 5.0% | EXCELENTE |
| **Overhead Medio de Decisión** | **0.474 ms** | < 10.0 ms | ULTRA RÁPIDO |
| **Overhead Máximo de Decisión** | **0.768 ms** | < 25.0 ms | ULTRA RÁPIDO |
| **Confianza Media del Router** | **0.9126** | >= 0.80 | CONSISTENTE |
| **Confianza Mínima Registrada** | **0.8400** | >= 0.80 | CONSISTENTE |
| **Fugas con Nemotron Deshabilitado** | **0** | 0 estrictamente | CERTIFICADO |

### Desglose por Categoría

| Categoría | Casos | Exactitud | Confianza Media | Latencia Decisión | Distribución de Modelos Elegidos |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **FAST_INTERACTION** | 10 | 100.0% | 0.947 | 0.507 ms | Gemma 4 e4b: **10** (100%) |
| **TECHNICAL** | 10 | 100.0% | 0.930 | 0.425 ms | Qwen3 8B: **10** (100%) |
| **COMPLEX_REASONING**| 10 | 100.0% | 0.890 | 0.491 ms | Nemotron 3 Ultra: **10** (100%)* |
| **AGENT_PLANNING** | 10 | 100.0% | 0.910 | 0.448 ms | Nemotron 3 Ultra: **10** (100%)* |
| **OFFLINE** | 5 | 100.0% | 0.932 | 0.494 ms | Qwen3 8B: **3**, Gemma 4: **2**, Nemotron: **0** |
| **AMBIGUOUS** | 5 | 100.0% | 0.840 | 0.506 ms | Gemma 4 e4b: **5** (100%) |

*\*Nota: Seleccionado en modo experimental únicamente cuando `NEMOTRON_ENABLED=true`.*

---

## 6. EVALUACIÓN DE RESILIENCIA Y CADENA DE FALLBACK

Se evaluó la cadena de fallback determinista (`execute_with_fallback`) ante escenarios de falla remota y local:

```text
NVIDIA Nemotron 3 Ultra
           │
           ▼ (si falla: Timeout / ConnectionError)
       Qwen3 8B
           │
           ▼ (si falla: SocketError / InferenceError)
      Gemma 4 e4b
           │
           ▼ (si falla todo)
  InferenceError Formal (NUNCA éxito falso)
```

### Resultados de Simulaciones de Falla:
1. **Modelo Primario Exitoso:** Cuando Nemotron responde normalmente, se ejecuta en 1 intento sin invocar fallback.
2. **Timeout de Nemotron (`ProviderTimeoutError` tras 30s):** La ejecución salta de inmediato a `qwen3:8b`, completando la solicitud sin bloquear indefinidamente JESSYCA.
3. **Falla de Conexión Remota (`ProviderConnectionError` / Red Caída):** El router conmuta limpiamente a `qwen3:8b`.
4. **Falla Concurrente de Nemotron y Qwen:** La ejecución cascada a `gemma4:e4b` local, respondiendo en modo de degradación controlada.
5. **Falla Total de la Cadena:** Si todos los modelos fallan, se propaga `InferenceError`. **En ningún caso se emite una respuesta tipo "Listo" o falso éxito.**

---

## 7. PRUEBAS DE NO-REGRESIÓN Y SUITE EXISTENTE

Se ejecutó la totalidad de pruebas automáticas del proyecto:

```text
pytest tests/router tests/llm -q
```

**Resultado:**
- **Suite del Router (`tests/router`):** 68 passed / 0 failed (100%)
- **Suite de LLM Existente (`tests/llm`):** 31 passed / 0 failed (100%)
- **Total:** **99 tests passed, 0 failed en 6.64s.**

No se detectó ninguna regresión en el catálogo de modelos, los adaptadores ni los proveedores existentes.

---

## 8. CONCLUSIONES BASADAS EN EVIDENCIA

Basado estrictamente en los datos empíricos obtenidos en los benchmarks de las Fases 2 y 3:

1. **Eficiencia del Overhead:** El proceso de clasificación contextual del router añade un promedio de **0.474 ms**, lo cual es despreciable (<0.15%) comparado con el tiempo de inferencia de cualquier modelo (320 ms a 1766 ms).
2. **Alineación de Modelos por Tarea:**
   - Para las 10 tareas de **Fast Interaction**, el router seleccionó **Gemma 4 e4b en 10 de 10 casos (100%)**, asegurando la respuesta de menor latencia.
   - Para las 10 tareas **Técnicas y de Código**, el router seleccionó **Qwen3 8B en 10 de 10 casos (100%)**.
   - Para las 20 tareas de **Razonamiento Complejo y Agent Planning**, cuando Nemotron estuvo habilitado, el router lo seleccionó en **20 de 20 casos (100%)**. Cuando Nemotron estuvo deshabilitado (`NEMOTRON_ENABLED=false`), el router seleccionó a **Qwen3 8B en 20 de 20 casos (100%)**, demostrando aislamiento estricto y cero fugas hacia la API remota.
   - En situaciones **Offline**, el router excluyó a Nemotron en **5 de 5 casos (100%)**, repartiendo la carga entre Qwen3 8B y Gemma 4 e4b.
   - Para órdenes **Ambiguas**, el router seleccionó a **Gemma 4 e4b en 5 de 5 casos (100%)** para realizar aclaraciones rápidas sin coste remoto.
3. **Recomendación para Producción:** Mantener el router en modo `SHADOW` (`MODEL_ROUTER_MODE=shadow`) durante la operación regular para continuar recopilando telemetría de decisiones antes de evaluar una activación de enrutamiento real en el bucle principal.
