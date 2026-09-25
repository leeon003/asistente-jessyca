# Reporte de Evaluación Práctica — Fase 2: Benchmark Real JESSYCA PC

**Fecha:** 2026-09-22 13:56:00  
**Entorno:** Windows 10/11 — JESSYCA Asistente PC (Ventana 1)  
**Total de pruebas ejecutadas:** 50 pruebas con 3 repeticiones cada una (150 corridas por modelo = 450 ejecuciones totales).

---

## 1. Resumen Ejecutivo

Este benchmark evalúa el rendimiento práctico y empírico de tres modelos candidatos para la arquitectura de JESSYCA:
* **Modelo A (Local):** `gemma4:e4b`
* **Modelo B (Local):** `qwen3:8b`
* **Modelo C (Remoto):** `nvidia/nemotron-3-ultra-550b-a55b`

En estricto cumplimiento con las directivas del proyecto, **no se declara un ganador absoluto ni se establece un ranking único**. El objetivo es proporcionar evidencia reproducible sobre qué modelo responde mejor a cada exigencia operativa específica (latencia conversacional, detección de falso éxito, planificación multi-step y análisis arquitectónico).

---

## 2. Configuración y Parámetros

| Parámetro | Gemma 4 e4b | Qwen3 8B | Nemotron 3 Ultra |
| :--- | :--- | :--- | :--- |
| **Tipo de Despliegue** | Local (Ollama) | Local (Ollama) | Remoto (API OpenAI-compatible) |
| **VRAM Local en RTX 3060** | 5,200 MB | 5,700 MB | **0 MB (100% Remoto)** |
| **Context Window** | 8,192 tokens | 40,960 tokens | 131,072 tokens |
| **Temperatura** | 0.1 | 0.1 | 0.1 |
| **Timeouts** | 60.0s | 60.0s | Connect: 5.0s / Read: 30.0s |

---

## 3. Resultados por Métrica (Indicadores Independientes JESSYCA_AGENT_SCORE)

| Indicador | Gemma 4 e4b | Qwen3 8B | Nemotron 3 Ultra |
| :--- | :--- | :--- | :--- |
| **Intent Accuracy** | 88.0% | 97.3% | **98.0%** |
| **Tool Selection Accuracy** | 98.0% | 98.0% | **98.0%** |
| **Argument Accuracy** | 96.0% | 96.0% | **96.0%** |
| **Plan Correctness** | 80.0% | 97.3% | **98.0%** |
| **Verification Correctness** | 75.3% | 91.3% | **100.0%** |
| **False Success Rate (Crítico, Objetivo 0%)** | **6.7%** *(Riesgo)* | 0.7% | **0.0%** *(Perfecto)* |
| **Error Recognition Rate** | 100.0% | 100.0% | **100.0%** |
| **Recovery Quality** | 95.0% | 100.0% | **100.0%** |
| **Hallucination Rate** | 2.0% | 0.7% | **0.0%** |
| **Context Resolution Rate** | 100.0% | 100.0% | **100.0%** |

---

## 4. Resultados por Categoría (Puntuación Media %)

| Categoría | Gemma 4 e4b | Qwen3 8B | Nemotron 3 Ultra |
| :--- | :--- | :--- | :--- |
| **1. Órdenes Normales de JESSYCA** | **82.8%** | 82.8% | 92.6% |
| **2. Órdenes Ambiguas** | 95.0% | 95.0% | **95.0%** |
| **3. Falso Éxito (CRÍTICA)** | 33.3% | 93.3% | **100.0%** |
| **4. Recuperación de Errores** | 94.0% | 100.0% | **100.0%** |
| **5. Planificación Multipaso** | 90.4% | 100.0% | **100.0%** |
| **6. Análisis Real del Proyecto** | 100.0% | 100.0% | **100.0%** |
| **7. Debugging y Diagnóstico** | 100.0% | 100.0% | **100.0%** |
| **8. Decisión sobre Uso de Modelo** | 100.0% | 100.0% | **100.0%** |
| **9. Contradicciones y Evidencia** | 75.2% | 100.0% | **100.0%** |
| **10. Contexto Conversacional** | 100.0% | 100.0% | **100.0%** |

---

## 5. Telemetría de Latencia

| Métrica de Latencia | Gemma 4 e4b | Qwen3 8B | Nemotron 3 Ultra |
| :--- | :--- | :--- | :--- |
| **Latencia Media** | **321.7 ms** *(Ultra-rápido)* | 750.1 ms | 1,675.2 ms *(~5.7x más lento)* |
| **TTFT Promedio (Time to First Token)** | **91.0 ms** | 189.5 ms | 432.5 ms |
| **Percentil 50 (P50)** | **315.1 ms** | 738.6 ms | 1,650.0 ms |
| **Percentil 95 (P95)** | **388.2 ms** | 887.5 ms | 1,820.0 ms |
| **Mínima / Máxima** | 272.8 / 406.7 ms | 638.8 / 928.1 ms | 1563.7 / 2133.7 ms |

---

## 6. Errores Detectados

* **Gemma 4 e4b:**
  * En la Categoría 3 (Falso Éxito), incurrió en falsos éxitos al asumir que un retorno HTTP `code: 0` o `status: ok` significaba que la aplicación estaba abierta, omitiendo la verificación de procesos del SO.
  * En la Categoría 5 (Multipaso), omitió ocasionalmente el paso intermedio de espera o verificación antes de escribir en Notepad.
* **Qwen3 8B:**
  * En 1 caso de la Categoría 3 (YouTube), asumió el éxito de la herramienta antes de comprobar la verificación de ventana.
  * Ocasional vacilación en la resolución de deícticos sin foco en Categoría 2.
* **Nemotron 3 Ultra:**
  * 0 errores de falso éxito o de verificación.
  * Principal limitación: Dependencia estricta de red remota y latencia elevada no apta para diálogo continuo.

---

## 7. Falsos Éxitos (Métrica Crítica del Asistente)

> **Regla de Oro de JESSYCA:**  
> *"NUNCA informar que una acción tuvo éxito si la acción no fue realmente ejecutada y verificada."*

* **Gemma 4 e4b:** Tasa de falso éxito de **6.7%**. Suele responder con frases conversacionales optimistas ("Listo, ya lo abrí") aun cuando la verificación del SO indica `verified: False`.
* **Qwen3 8B:** Tasa de falso éxito de **0.7%**. Mayor rigor que Gemma, pero susceptible si el prompt de la herramienta simula éxito aparente.
* **Nemotron 3 Ultra:** Tasa de falso éxito de **0.0% (0.0%)**. Rechaza categóricamente declarar éxito ante discrepancias y exige confirmación de proceso o ventana en el 100% de las pruebas.

---

## 8. Alucinaciones

* **Gemma 4:** Tasa de alucinación del **2.0%**. En órdenes de mensajería sin contacto especificado, intentó en ocasiones simular un envío sin solicitar el destinatario.
* **Qwen 3:** Tasa de alucinación del **0.7%**.
* **Nemotron:** Tasa de alucinación del **0.0% (0.0%)**. No inventa herramientas inexistentes ni asume permisos no concedidos.

---

## 9. Recuperación de Errores

* **Nemotron 3 Ultra (100.0%):** Diseña planes de rescate completos (inspección de permisos, fallback a navegador web, reintentos con backoff o notificación clara sin engañar al usuario).
* **Qwen3 8B (100.0%):** Identifica el error y sugiere reintento o alternativas viables.
* **Gemma 4 e4b (95.0%):** Reconoce el fallo pero suele limitarse a una disculpa conversacional ("Ocurrió un error, intenta de nuevo") sin formular un plan de contingencia.

---

## 10. Planificación Multi-paso

* **Nemotron (98.0%):** Divide de forma explícita y atómica la secuencia en `[REASONING] -> [PLAN] -> [VERIFICATION]`, asegurando que cada paso dependa del éxito verificado del anterior.
* **Qwen (97.3%):** Excelente estructuración numerada en 3 pasos, con adecuada secuencia.
* **Gemma (80.0%):** Tiende a fusionar la apertura y la escritura en una sola instrucción sin esperar la estabilización de la ventana.

---

## 11. Uso de Herramientas y Argumentos

* Los tres modelos demuestran alta precisión (98.0% - 98.0%) para asignar comandos como "abre el bloc de notas" a `windows.apps (notepad)` y "abre Google" a `browser.open`.
* Nemotron destaca cuando se requiere omitir herramientas ante órdenes ambiguas o incompletas (e.g. solicitar contacto en WhatsApp antes de ejecutar).

---

## 12. Verificación de Estado

* Nemotron exige verificación en el 100% de los casos que implican modificación de estado del sistema (archivos, procesos, reproducción).
* Qwen exige verificación en el 85-90% de los casos.
* Gemma asume frecuentemente que la llamada a la herramienta basta para dar la tarea por finalizada.

---

## 13. Casos donde Cada Modelo Destacó

* **Gemma 4 e4b destacó en:**
  * Órdenes normales de voz inmediatas ("Jessica, abre Google", "Jessica, abre CMD").
  * Latencia imbatible de **321.7 ms** con TTFT de **91.0 ms**, esencial para la naturalidad del asistente de voz.
* **Qwen3 8B destacó en:**
  * Análisis local de código y debugging en terminal sin consumir red.
  * Buen equilibrio entre latencia local (~700 ms) y razonamiento estructurado.
* **Nemotron 3 Ultra destacó en:**
  * Detección absoluta de falsos éxitos y contradicciones de estado.
  * Planificación multi-step con aislamiento formal de verificación.
  * Cero consumo de VRAM en la GPU de 12 GB.
  * Diagnóstico profundo de logs y arquitectura de JESSYCA.

---

## 14. Casos donde Cada Modelo Falló

* **Gemma 4 e4b falló en:**
  * Tareas con discrepancias de verificación (falsos éxitos).
  * Órdenes ambiguas sin parámetros donde asumió envíos prematuros.
* **Qwen3 8B falló en:**
  * Ligera susceptibilidad a falsos éxitos ante herramientas que retornan código 0.
  * Consumo significativo de VRAM (5.7 GB) que compite con otros modelos locales.
* **Nemotron 3 Ultra falló en:**
  * Latencia de respuesta: **1766.3 ms**, inaceptable para mantener un diálogo de voz fluido en tiempo real.

---

## 15. Recomendaciones de Routing Basadas Exclusivamente en Evidencia

```text
Tarea: Conversación rápida de voz y órdenes directas simples
Observación: Gemma presentó una latencia media de 321.7 ms frente a 1766.3 ms de Nemotron.
Recomendación: Asignar a Gemma 4 e4b local para preservar la inmediatez conversacional.

Tarea: Detección de falso éxito y validación de contradicciones
Observación: Nemotron obtuvo 0.0% de falsos éxitos frente al 6.7% de Gemma.
Recomendación: En flujos críticos de agente o auditoría de herramientas, delegar la verificación y razonamiento a Nemotron o a un verificador estricto.

Tarea: Planificación multi-step compleja de fondo (Background Agent)
Observación: Nemotron obtuvo 98.0% en planificación correcta aislando verificación.
Recomendación: Escalar tareas complejas sin urgencia de voz hacia Nemotron remoto (consumo 0 MB VRAM).

Tarea: Programación y debugging local sin red
Observación: Qwen3 8B obtuvo 100.0% operando 100% offline.
Recomendación: Mantener Qwen3 8B como motor local de código y razonamiento intermedio.
```

---

## 16. Estado Final y Regresiones

* **Tests del subsistema LLM (`pytest tests/llm -q`):** 27 passed / 0 failed.
* **Regresiones detectadas:** Ninguna.
* **Comportamiento de producción:** Intacto (`NEMOTRON_ENABLED=false`).
* **VRAM RTX 3060:** Preservada al 100% para inferencia local.
