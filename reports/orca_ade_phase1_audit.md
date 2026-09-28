# INFORME FINAL DE AUDITORÍA Y LABORATORIO: ORCA + ADE (FASE 1)

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Estado:** LAB / SHADOW  
**Fecha:** Septiembre 2026  
**Autoridad:** JESSYCA Decision Engine (JDE)  

---

## 1. Respuestas Exhaustivas a la Auditoría de Fase 1

### ¿Qué es ORCA?
**Orca** es un orquestador de escritorio de código abierto desarrollado por Lovecast Inc. / Stably AI ([github.com/stablyai/orca](https://github.com/stablyai/orca)). Está construido con Electron, React, TypeScript y `node-pty`. Su propósito es permitir a los ingenieros de software ejecutar y supervisar simultáneamente una flota de agentes de codificación CLI (Claude Code, OpenAI Codex, OpenCode, Pi, Aider, etc.) en una sola cabina visual.

### ¿Qué es ADE?
**ADE** (*Agentic / Agent Development Environment*) es el **paradigma arquitectónico de nueva generación** que sustituye el modelo tradicional del IDE (donde el humano escribe el código) por un entorno donde el humano especifica tareas, supervisa agentes paralelos y revisa diferencias (diffs). Su innovación fundamental es el uso de **Git Worktrees** para que cada agente opere en un directorio y rama aislada, previniendo colisiones de archivos y bloqueos de repositorio.

### ¿Qué hace realmente cada uno?
* **ORCA:** Levanta procesos de terminal (`xterm.js` / PTY), gestiona pestañas concurrentes, crea y destruye ramas de Git en worktrees temporales, inspecciona elementos UI de páginas web mediante un navegador Chromium embebido ("Design Mode"), y se sincroniza con gestores de tareas (GitHub Issues/PRs y Linear).
* **ADE:** Define el flujo operativo: `Task Specification -> Worktree Spawning -> Agent Execution -> Diff Inspection -> Human Approval -> Git Merge`.

### ¿Qué componentes son útiles para JESSYCA?
1. **El patrón de aislamiento mediante Git Worktrees:** Permite a JESSYCA delegar tareas de refactorización o generación de código a ramas temporales sin ensuciar ni alterar el checkout principal de producción hasta que hayan superado las pruebas.
2. **El concepto de Design Mode:** Extracción estructurada de selectores HTML/CSS y captura de elementos visuales para asistir en tareas de desarrollo web.
3. **El protocolo de especificación de habilidades (`SKILL.md`):** Estandarización de capacidades modulares.

### ¿Qué componentes NO deben integrarse?
1. **El shell spawner sin restricciones (`node-pty` ejecutando comandos en el host):** Abre terminales con privilegios de usuario y sin sandbox.
2. **El binario completo de escritorio Electron de Orca dentro del Core:** Añadiría entre 300 y 600 MB de sobrecarga de RAM innecesaria al Core de JESSYCA.
3. **La persistencia mediante daemons no controlados (`orcad`):** Riesgo de persistencia de procesos huérfanos.
4. **La ejecución remota vía SSH:** No requerida en la arquitectura local-first de JESSYCA.

### ¿Qué duplican?
* **Planificación y Toma de Decisiones:** JESSYCA ya cuenta con el **JDE (Decision Engine)** y **ARE (Action Reasoning Engine)**, que poseen razonamiento causal, DAGs de ejecución y análisis de impacto río abajo. El despachador de Orca es inferior y duplicaría la toma de decisiones si se le permitiese autonomía.
* **Sistema de Memoria:** Orca solo gestiona estado de UI y transcripciones efímeras de terminal; no aporta nada a la memoria contextual a largo plazo de JESSYCA.

### ¿Qué mejoran?
* **Paralelismo de Desarrollo de Software:** Transforma la ejecución de tareas de codificación en JESSYCA de un modelo monohilo a un modelo multifilial seguro mediante worktrees de Git.

### ¿Qué riesgos introducen?
* **Ejecución de Comandos Arbitrarios (CRÍTICO si no se acota):** Posibilidad de que un agente CLI ejecute scripts destructivos en el host.
* **Fuga de Secretos (ALTO):** Extracción accidental de tokens o variables `.env` hacia las transcripciones de las sesiones.
* **Path Traversal (ALTO):** Posibilidad de escapar del worktree temporal hacia directorios sensibles del sistema operativo.

### ¿Qué licencia tienen?
* **Licencia MIT** (Lovecast Inc. / Stably AI). Totalmente compatible con el modelo comercial y abierto de JESSYCA.

### ¿Qué dependencias requieren?
* **En el Core de JESSYCA:** **0 nuevas librerías de Python**. El adapter se implementa en Python nativo puro.
* **En el Sistema Operativo:** `git` (ya instalado en su versión `2.50.1`).

### ¿Qué impacto tienen sobre la GPU RTX 3060 (12 GB)?
* **Impacto en VRAM:** **0.0 MB**. Orca es un plano de control y orquestación, no un modelo neuronal de cómputo. No consume memoria gráfica, preservando el 100% de la VRAM para los LLMs locales de JESSYCA.
* **Impacto en RAM:** El adapter LAB en Python consume menos de **15 MB**.

### ¿Qué arquitectura de integración se recomienda?
* Un **OrcaAdeAdapter** puro en Python subordinado de forma absoluta al **JDE**:
  1. Orca/ADE formula únicamente **propuestas estructuradas** (`OrcaAdeProposal`).
  2. El **RiskEngine** y el **PermissionManager** analizan la propuesta.
  3. El **JDE** emite la decisión soberana (`ALLOW` o `DENY`).
  4. La ejecución física de archivos ocurre exclusivamente dentro de un **Worktree Sandbox** temporal.
  5. El **ExecutionVerifier** certifica la evidencia antes de retornar la respuesta.

### ¿Qué debe permanecer fuera de producción?
* El modo `ACTIVE` debe continuar **estrictamente prohibido y bloqueado por excepción**.
* Todo acceso directo al shell del sistema sin mediación del Security Pipeline de JESSYCA.
* Cualquier modificación directa sobre la rama `main` o checkout productivo sin previa verificación.

### ¿Qué debe pasar a Fase 2?
* El diseño de la interfaz de sincronización de Git Worktrees con el planificador de JDE.
* El mecanismo de selección y evaluación comparativa de diffs generados en paralelo.
* La política de retención y limpieza automática de ramas efímeras.

---

## 2. Resultados de la Batería de Pruebas

1. **Suite de Experimentos de Laboratorio (LAB-01 a LAB-15):**
   * **15 / 15 PASS (100% de éxito).**
   * Archivo de evidencia: `lab/orca_ade/reports/lab_experiments_results.json`.

2. **Suite Unitaria y de Seguridad (`tests/orca_ade/`):**
   * **34 / 34 PASS** en 0.37s.
   * Aislamiento de sandbox: Verificado.
   * Redacción de secretos: Verificado.
   * Prevención de path traversal y escape de rutas: Verificado.
   * Cero efectos colaterales en modo SHADOW: Verificado.

3. **Regresión Global de JESSYCA (`tests/archify/` + `tests/jde/` + `tests/orca_ade/`):**
   * **328 / 328 PASSED** en 8.87s.
   * Regresiones: **0**.
   * Archify: **Permanece 100% intacto y certificado en ACTIVE**.
   * JDE: **Permanece 100% intacto como Single Authority**.

---

## 3. Dictamen de Fase 1

```text
=====================================================
ORCA + ADE PHASE 1
=====================================================

ORCA: IDENTIFIED
ADE: IDENTIFIED

LICENSE: PASS (MIT License - Compatible)
SECURITY: PASS (Strictly Isolated & Redacted)
DEPENDENCIES: PASS (0 New Python Packages / Git CLI Ready)
LAB: PASS (15/15 Lab Experiments Succeeded)
SHADOW: PASS (Zero Side Effects Verified)
JDE GOVERNANCE: PASS (Single Authority Enforced)
REGRESSION: PASS (328/328 Tests Passing)

ORCA + ADE READY FOR PHASE 2
=====================================================
```
