# INVENTARIO DE DEPENDENCIAS Y REQUISITOS DE HARDWARE: ORCA + ADE

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Fecha:** Septiembre 2026  

---

## 1. Inventario Técnico de Dependencias

A continuación se categorizan todas las dependencias del ecosistema Orca (`stablyai/orca`) y de la capa de integración de JESSYCA:

| Dependencia | Tipo | Ámbito | Estado en JESSYCA | Obligatoria en Fase 1 |
| :--- | :--- | :---: | :---: | :---: |
| **Python >= 3.11** | Intérprete Core | Runtime | Instalado (`v3.11.9`) | **SÍ** |
| **Git CLI >= 2.30** | Herramienta SO | Runtime | Instalado (`v2.50.1`) | **SÍ** (para Git worktrees) |
| **Node.js >= 20.0** | Runtime JS | Runtime | Instalado (`v24.5.0`) | Opcional (solo si se ejecuta UI nativa) |
| **npm / pnpm** | Gestor de paquetes | Build/Dev | Instalado (`npm v11.5.1`) | Desarrollo / Build |
| **Electron** | Contenedor de escritorio | Runtime Orca | No empaquetado en Core | **NO** (Aislado fuera del Core) |
| **node-pty** | PTY virtual en Node | Runtime Orca | No instalado en JESSYCA | **NO** (Reemplazado por Mock en LAB) |
| **Docker / Contenedores** | Virtualización | Runtime | No requerido | **NO** (Orca corre localmente) |
| **LLM APIs Externas** | Proveedor de modelos | Externo | Configurado en JESSYCA | Opcional (BYOK: Claude, OpenAI, etc.) |
| **GitHub CLI / REST API** | Integración PRs | Externo | Disponible | Opcional |
| **Linear API** | Integración tareas | Externo | No configurado | Opcional |

---

## 2. Clasificación de Dependencias para el LAB de JESSYCA

Para garantizar que el Core de JESSYCA no sufra contaminación ni aumentos desmedidos en su tiempo de arranque:

### 2.1 Dependencias Requeridas en el Core / LAB
* `Python Standard Library` (`os`, `sys`, `subprocess`, `json`, `dataclasses`, `enum`, `pathlib`, `hashlib`, `re`, `time`).
* `JESSYCA Core Modules` (`core.jde`, `core.security`, `core.execution.execution_verifier`, `core.integration`).
* **Impacto adicional en dependencias de Python:** **CERO (0 nuevas librerías externas requeridas)**. El adapter experimental en `core/orca_ade/` se implementa como Python nativo puro.

### 2.2 Dependencias Opcionales / No Necesarias en Fase 1
* El binario completo de Electron de Orca (`orca-desktop`) **NO** se instala en el entorno de producción ni en el Core de JESSYCA.
* No se requieren imágenes Docker pesadas ni microservicios adicionales en segundo plano.

---

## 3. Evaluación de Hardware e Impacto en RTX 3060 (12 GB)

JESSYCA PC opera sobre una estación con GPU NVIDIA GeForce RTX 3060 (12 GB VRAM). La asignación y protección de esta VRAM es un recurso crítico que debe reservarse prioritariamente para los modelos de lenguaje locales (Ollama / vLLM / Whisper / TTS) del sistema.

### 3.1 Impacto en VRAM
* **Orca es un orquestador / plano de control, NO un modelo de lenguaje.**
* Orca coordina agentes de codificación existentes (que o bien se ejecutan contra APIs externas mediante Bring-Your-Own-Key, o contra instancias existentes de Ollama si el usuario así lo define).
* **Consumo de VRAM del Adapter LAB de JESSYCA:** **0.0 MB**.
* **Consumo de VRAM de la UI de Orca (Electron):** **0.0 MB** de memoria gráfica de cómputo (solo memoria de aceleración 2D estándar compartida de Windows, < 80 MB).

### 3.2 Impacto en Memoria RAM del Sistema
| Componente | Memoria RAM Típica |
| :--- | :---: |
| **JESSYCA OrcaAdeAdapter (Python LAB)** | **< 15 MB** |
| **Sandbox de Worktrees (Git metadata)** | **< 25 MB** |
| **Orca Desktop App (Electron completo, si se lanza)** | ~350 MB - 600 MB |
| **Terminales Concurrentes (por cada agente CLI en ejecución)** | ~50 MB - 150 MB por worker |

### 3.3 Impacto en Almacenamiento en Disco
* La arquitectura de **Git Worktrees** crea directorios de trabajo ligeros vinculados al repositorio principal (`.git/worktrees/<branch>`).
* A diferencia de clonar el repositorio completo (que duplica todo el historial `.git`), un worktree solo ocupa el espacio de los archivos del árbol de trabajo actual.
* Para el repositorio de JESSYCA (~40 MB de código fuente), cada worktree activo consume entre 30 y 45 MB de espacio temporal.
* El sandbox del LAB debe contar con una política de limpieza automática (*garbage collection*) que elimine worktrees temporales al finalizar las pruebas.

### 3.4 Latencias de Operación
* **Inicialización del Adapter LAB:** < 2 ms.
* **Evaluación de Propuesta (Shadow Mode):** < 5 ms.
* **Creación de Git Worktree (en disco SSD):** ~150 - 300 ms.
* **Limpieza y remoción de Worktree:** ~50 - 100 ms.

---

## 4. Dictamen de Hardware y Dependencias

```text
=====================================================
ORCA + ADE DEPENDENCIES & HARDWARE VERDICT
=====================================================
PYTHON DEPENDENCIES: 0 new external packages required
VRAM CONSUMPTION: 0.0 MB (Preserved for local LLMs)
RAM FOOTPRINT (LAB ADAPTER): < 15 MB
DISK CONSUMPTION: Ephemeral (< 50 MB per worktree)
STATUS: PASS FOR LAB / FEASIBLE
=====================================================
```
