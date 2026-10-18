# JESSYCA BRAIN 1.0 — FASE 7: EVALUACIÓN Y SELECCIÓN DE MODELOS DE INFERENCIA

**Fecha de Evaluación:** 16 de Octubre de 2026  
**Servidor de Modelos:** Ollama `localhost:11434`  
**Objetivo:** Determinar la combinación óptima de modelo principal y modelos auxiliares para el funcionamiento cotidiano de JESSYCA como asistente personal.

---

## 1. COMPARATIVA MULTIDIMENSIONAL DE MODELOS

| Dimensión de Evaluación | `llama3.2:latest` (3.2B) | `qwen3:8b` (8B) | `qwen3-vl:4b` (4B Multimodal) | `gemma4:e4b` (9.6B) |
| :--- | :---: | :---: | :---: | :---: |
| **Tamaño en Disco / VRAM** | **2.0 GB / 2.1 GB** | 5.2 GB / 5.2 GB | 3.3 GB / 3.3 GB | 9.6 GB / 8.8 GB |
| **Comprensión del Español** | **Excelente** (Natural y directo) | **Excelente** (Rico en matices) | **Muy Buena** | Buena (conciso en exceso) |
| **Latencia Primer Token** | **~480 ms** | ~1,150 ms | ~750 ms | ~1,850 ms |
| **Velocidad de Generación** | **118 – 127 t/s** | 55 – 59 t/s | 91 – 96 t/s | 32 – 41 t/s |
| **Generación JSON Estructurado**| **98% válido** | **100% válido** | 95% válido | 92% válido |
| **Razonamiento Lógico Profundo** | Bueno (óptimo para rutinas) | **Excelente** (cálculo y deducción) | Bueno | Muy Bueno |
| **Capacidades Multimodales (Visión)**| No (solo texto) | No (solo texto) | **Sí (Visión y OCR)** | No (solo texto) |
| **Huella Térmica / CPU** | **Baja (silencioso)** | Moderada | Baja | Alta |

---

## 2. ARQUITECTURA DE MODELOS SELECCIONADA PARA PRODUCCIÓN

```
┌─────────────────────────────────────────────────────────────┐
│                 ENRUTADOR DE MODELOS JESSYCA                │
└──────────────────────────────┬──────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
┌──────────────┐        ┌──────────────┐        ┌──────────────┐
│  PRINCIPAL   │        │   AUXILIAR   │        │   AUXILIAR   │
│  llama3.2    │        │   qwen3:8b   │        │ qwen3-vl:4b  │
├──────────────┤        ├──────────────┤        ├──────────────┤
│ • Voz E2E    │        │ • Planes DAG │        │ • Capturas   │
│ • Diálogo    │        │   Complejos  │        │   Pantalla   │
│ • Herramien- │        │ • Auditoría  │        │ • OCR UI     │
│   tas básicas│        │   Lógica     │        │ • Inspección │
└──────────────┘        └──────────────┘        └──────────────┘
```

### 2.1 Modelo Principal: `llama3.2:latest`
* **Motivación:** Ofrece la menor latencia de respuesta (< 3.0 segundos para la respuesta completa por voz), velocidad superior a 118 tokens/segundo y excelente comprensión del español hablado y escrito. Su reducida huella de 2 GB de VRAM permite que Windows 11 y aplicaciones de usuario (juegos, diseño, ofimática) corran sin degradación gráfica.

### 2.2 Modelo Auxiliar de Planificación Compleja: `qwen3:8b`
* **Motivación:** Utilizado cuando una orden requiere descomponerse en más de 4 submetas con dependencias condicionales o cálculo matemático avanzado.

### 2.3 Modelo Auxiliar Visual: `qwen3-vl:4b`
* **Motivación:** Invocado para tareas de inspección de interfaz gráfica cuando las APIs de accesibilidad UIA no retornan identificadores de control legibles.
