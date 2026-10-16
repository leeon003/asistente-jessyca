# JESSYCA 4.0 — FASE 0: BASELINE TÉCNICO Y ESTADO INICIAL DEL SISTEMA

**Fecha de Generación:** 16 de Octubre de 2026  
**Rama de Desarrollo:** `feature/jessyca-4-agent`  
**Commit Base:** `ad1feb3149e5605022e358ff7efe61ac82aa1125` (`docs(eval): completar Etapa 7 y consolidar REPORTE_FINAL de evaluacion de agentes de pantalla`)  
**Repositorio Remoto:** [https://github.com/leeon003/asistente-jessyca.git](https://github.com/leeon003/asistente-jessyca.git)  
**Alcance:** Asistente Personal para Windows (Exclusivamente escritorio, voz, investigación, automatización de apps y CUA; cero componentes comerciales/CRM).

---

## 1. Entorno de Hardware y Sistema Operativo

| Componente | Especificación Detectada | Estado / Observación |
|---|---|---|
| **Sistema Operativo** | Microsoft Windows 11 Pro (Build 10.0.26200) | Validado vía `Win32_OperatingSystem`. Soporta sesión gráfica nativa y APIs Win32. |
| **Procesador (CPU)** | AMD64 Family 25 Model 33 Stepping 2 | 12 núcleos físicos / 24 hilos lógicos. Alto rendimiento multi-hilo para STT/TTS local. |
| **Memoria RAM** | 31.93 GB Total (16.63 GB disponibles) | Capacidad suficiente para mantener LLMs de 8B cuantizados en memoria conjunta. |
| **Tarjeta Gráfica (GPU)** | NVIDIA GeForce RTX 3060 (12 GB VRAM dedicada) | VRAM Libre: 10,415 MB. Driver NVIDIA 610.88. Aceleración CUDA disponible. |
| **Python** | 3.11.9 64-bit (`C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe`) | Entorno de ejecución principal del proyecto. |
| **Ollama CLI** | Version 0.34.3 (`C:\Users\PC\AppData\Local\Programs\Ollama\ollama.EXE`) | CLI instalado. Servicio daemon administrable bajo demanda. |

---

## 2. Modelos de Lenguaje Locales (Inventario en Disco vs Pipeline)

### 2.1 Modelos Físicamente Instalados en Disco (`.ollama/models/manifests`)
Los modelos locales detectados en el almacenamiento del usuario son:
1. `gemma4:e4b`
2. `llama3.1:latest`
3. `llama3.2:latest`
4. `qwen3:8b`
5. `qwen3-vl:4b`

### 2.2 Modelos Configurados en el Pipeline de JESSYCA
En [`core/local_agent/local_agent.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/local_agent/local_agent.py#L3105-L3116) y [`core/llm/model_registry.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/llm/model_registry.py):
* **Tareas Rápidas y Herramientas Cotidianas:** `llama3.2` (3.2B) — Baja latencia (<2.5 GB VRAM).
* **Diálogo General y Conversación:** `llama3.1` (8B) — Razonamiento balanceado.
* **Investigación Multi-Paso y Análisis Técnico:** `gemma4:e4b` — Tareas de razonamiento extendido.
* **Visión y Análisis de Pantalla (CUA):** `qwen3-vl:4b` — Multimodal nativo para inspección gráfica.

---

## 3. Métricas de Rendimiento de Referencia (Baseline Measurements)

Mediciones empíricas tomadas en el entorno local antes de modificaciones estructurales:

| Métrica | Valor Obtenido | Umbral de Aceptación / Comentario |
|---|:---:|---|
| **Inicialización del Agente (`LocalAgent`)** | **57.58 ms** | Excelente (<100 ms). Singleton ligero sin carga pesada síncrona. |
| **Almacenamiento en Memoria Permanente** | **1.39 ms** | SQLite / motor de memoria persistente rápido. |
| **Recuperación de Memoria (Recall)** | **0.03 ms** | Prácticamente instantáneo en memoria local. |
| **Resolución de Intención Conversacional** | **2.39 ms** | Clasificación instantánea para saludos y consultas directas. |
| **Resolución de Acción Simple (Legacy Regex)** | **0.48 ms** | Extracción directa de slots para órdenes atómicas ("Abre bloc de notas"). |
| **Resolución Compuesta (SAI Deterministic)** | **4.8 ms** *(excl. timeout)* | Cuando no hay LLM daemon activo, el fallback determinista resuelve en <5 ms. |
| **Consumo de Memoria RSS del Proceso** | **89.00 MB** | Huella sumamente reducida en reposo (<100 MB). |

---

## 4. Estado de Pruebas de Regresión Seguras

Se ejecutaron **53 pruebas de regresión seguras** (sin interacción destructiva con el sistema operativo ni alteración de datos de usuario):

| Módulo / Suite | Pruebas | Resultado | Duración |
|---|:---:|:---:|:---:|
| `tests/intent/test_sai_intent_benchmark.py` | 10 | **PASÓ (100%)** | 28.7s |
| `tests/intent/test_sai_intent_integration.py` | 7 | **PASÓ (100%)** | 17.1s |
| `tests/router/test_shadow_mode.py` | 12 | **PASÓ (100%)** | 4.2s |
| `tests/jde/test_shadow_integration.py` | 10 | **PASÓ (100%)** | 6.8s |
| `tests/execution/test_execution_verification.py` | 14 | **PASÓ (100%)** | 8.7s |
| **Total Global de Regresión Segura** | **53 / 53** | **100% ÉXITO** | **65.53s** |

---

## 5. Control de Configuración y Feature Flags

* Se ha agregado la variable de configuración tipada [`INTENT_ENGINE_MODE`](file:///d:/JESSYCA%203.0/asistente-jessyca/config/settings.py#L133-L138) en `AppSettings` con soporte dinámico por variable de entorno:
  * `"legacy"` (Valor por defecto): Mantiene 100% inalterado el comportamiento anterior.
  * `"shadow"`: Registra métricas comparativas observacionales sin alterar la respuesta al usuario.
  * `"sai"`: Activa el catálogo progresivo y la descomposición multi-paso con fallback automático.
* Archivo de configuración sanitizada respaldado en `backups/effective_config_sanitized.json`.
