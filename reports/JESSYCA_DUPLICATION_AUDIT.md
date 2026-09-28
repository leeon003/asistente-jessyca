# JESSYCA PC — AUDITORÍA DE DUPLICACIONES Y SOLAPAMIENTOS
**Fecha:** 2026-09-27  
**Sistema:** JESSYCA PC  
**Objetivo:** Identificar redundancias arquitectónicas, capacidades solapadas y componentes candidatos a descarte o unificación para evitar desperdicio de desarrollo.

---

## 1. MATRIZ DE DUPLICACIONES Y SOLAPAMIENTOS

| Sistema A | Sistema B | Funcionalidad Común | Tipo de Relación | ¿Complementarios? | Acción Arquitectónica |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **AnyDoc Core** (`core/anydoc/`) | **Documents Skills** (`skills/documents_skills.py`) | Conversión e inspección de archivos a texto/Markdown | **DUPLICACIÓN TOTAL** (AnyDoc es estrictamente superior en 15 formatos, AST, sandbox y metadatos) | NO | **ANYDOC SUPERSEDES DOCUMENTS_SKILLS** (Retirar `documents_skills` o delegar internamente a AnyDoc). |
| **Jarvis Adapter** (`core/integration/adapters/jarvis_adapter.py`) | **Windows Skills** (`skills/windows_skills.py`) | Apertura/cierre de apps Windows, lectura/escritura de portapapeles | **DUPLICACIÓN TOTAL** | NO | **DO NOT IMPLEMENT / RETIRE JARVIS ADAPTER** (Las habilidades nativas de Windows son más robustas y no dependen de un stack externo). |
| **ARE Adapter** (`core/integration/adapters/are_adapter.py`) | **Skill Graph Planner** (`skills/skill_graph_planner.py`) | Descomposición de metas en DAG de tareas y validación de ejecución | **SOLAPAMIENTO PARCIAL** (ARE maneja diagnóstico y recuperación; SkillGraph maneja dependencias de herramientas) | SÍ | **MERGE / UNIFY** (Adoptar el modelo de DAG y recuperación de ARE como motor central del planificador de agentes). |
| **Computer Use Adapter** (`core/integration/adapters/computer_use_adapter.py`) | **Windows Skills** (`skills/windows_skills.py`) | Automatización de escritorio y manipulación de ventanas | **SOLAPAMIENTO FUNCIONAL** (Computer Use usa píxeles/coordenadas; Windows Skills usa APIs semánticas y procesos del OS) | SÍ | **KEEP BOTH (SEGREGATED)** (Windows Skills como estándar primario; Computer Use como fallback de último recurso para apps legacy sin API). |
| **Model Router 2.0** (`core/llm/model_router.py`) | **Experimental Router** (`core/llm/experimental_router.py`) | Clasificación de intenciones y asignación de modelos LLM | **DUPLICACIÓN TEMPORAL** (Experimental Router fue el prototipo de laboratorio para Fase 4-5) | NO | **MODEL ROUTER 2.0 SUPERSEDES EXPERIMENTAL** (Archivar `experimental_router.py` una vez consolidado el enrutador 2.0). |
| **WebUI Bridge** (`interfaces/webui_bridge/`) | **Mobile API** (`interfaces/mobile_api/`) | Exposición de endpoints HTTP/FastAPI para clientes externos | **SOLAPAMIENTO ESTRUCTURAL** (Dos servidores FastAPI independientes en puertos 8088 y 8765) | SÍ (por ahora) | **MERGE LATER** (Unificar en un único gateway FastAPI con routers segregados `/v1/chat/completions` y `/api/v1/mobile`). |
| **EdgeTTS Provider** (`services/voice_service.py`) | **PocketTTS Provider** (`services/voice_service.py`) | Síntesis de voz (TTS) | **COMPLEMENTARIOS** (EdgeTTS ofrece alta calidad online con `CamilaNeural`; PocketTTS es fallback 100% offline local) | SÍ | **KEEP BOTH** (Estrategia híbrida: primario online, contingencia offline). |

---

## 2. ANÁLISIS DETALLADO DE CASOS CRÍTICOS

### 2.1 Caso AnyDoc vs DocumentsConvertSkill
- **Evidencia en Código:**
  - `skills/documents_skills.py` contiene clases rudimentarias en Python usando librerías ad-hoc para leer texto plano o CSV.
  - `core/anydoc/` contiene un motor completo con bindings nativos optimizados, soporte para 15 extensiones (`.docx`, `.xlsx`, `.pptx`, `.pdf`, `.odt`, `.rtf`, `.epub`, etc.), detección por magic bytes, AST Markdown unificado y sandbox estricto.
- **Riesgo:** Confusión en el agente al seleccionar herramientas de lectura documental.
- **Decisión:** Declarar `skills/documents_skills.py` como componente **LEGACY** y redirigir toda la lectura de documentos a `core/anydoc/`.

### 2.2 Caso Jarvis Adapter vs Windows Skills
- **Evidencia en Código:**
  - `jarvis_adapter.py` expone `jarvis.get_clipboard`, `jarvis.set_clipboard`, `jarvis.open_app`, `jarvis.close_app`.
  - `skills/windows_skills.py` expone `windows.apps`, `windows.clipboard`, `windows.media`, `windows.screenshot`, `windows.audio`, `windows.display`.
  - Ambos atacan el mismo sistema operativo Windows con llamadas análogas de `psutil` y comandos del sistema.
- **Riesgo:** Mantenimiento redundante de un adaptador que imita un asistente externo cuando JESSYCA ya posee control nativo superior.
- **Decisión:** Mantener desactivado `jarvis_adapter.py` y descartarlo del roadmap productivo (**DO NOT IMPLEMENT**).

### 2.3 Caso ARE vs Nuevo Desarrollo de Razonamiento
- **Evidencia en Código:**
  - Existía la presunción histórica de que ARE no estaba iniciado o requería una fase de implementación desde cero.
  - En la auditoría se descubrió que `core/integration/adapters/are_adapter.py` ya está terminado, con 4 capacidades de descomposición, evaluación, diagnóstico y recuperación, y 28 tests unitarios pasando al 100%.
- **Riesgo:** Desperdiciar semanas recreando un subsistema que ya fue construido y probado.
- **Decisión:** No crear nada nuevo. Tomar el `are_adapter` existente y proceder directamente a su integración y gobierno con el JDE.

### 2.4 Caso Dualidad de Servidores FastAPI (WebUI Bridge y Mobile API)
- **Evidencia en Código:**
  - `interfaces/webui_bridge/` levanta un proceso Uvicorn en el puerto 8088 con endpoints estilo OpenAI.
  - `interfaces/mobile_api/` levanta otro proceso Uvicorn en el puerto 8765 con endpoints REST personalizados.
- **Riesgo:** Sobrecarga de puertos abiertos, mantenimiento duplicado de configuraciones CORS y middleware de seguridad.
- **Decisión:** A corto plazo, mantener ambos para no alterar el despliegue local actual. A medio plazo, converger en un API Gateway centralizado (`interfaces/gateway/`).
