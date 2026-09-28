# ARQUITECTURA TÉCNICA Y CAPABILITY MAPPING: ORCA + ADE

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Fecha:** Septiembre 2026  

---

## 1. Identificación y Definición Arquitectónica

### 1.1 ¿Qué es ORCA?
**Orca** (desarrollado por Lovecast Inc. / Stably AI) es un **Agentic Development Environment (ADE)** de código abierto y un orquestador de escritorio diseñado para supervisar y ejecutar múltiples agentes de codificación autónomos en paralelo (tales como Claude Code, Codex, OpenCode, Pi, Aider, etc.). 

A diferencia de un IDE tradicional (centrado en la escritura manual de código por un humano) o de un agente monolítico (que ejecuta secuencias de comandos en un solo directorio), Orca proporciona una **cabina de control y plano de orquestación**.

### 1.2 ¿Qué es ADE?
**ADE** (*Agentic / Agent Development Environment*) es el **paradigma arquitectónico** que transforma el desarrollo de software:
- En lugar de que el desarrollador escriba código directamente, el desarrollador **especifica, supervisa y revisa**.
- El ADE gestiona el aislamiento de los agentes mediante **Git Worktrees**, evitando colisiones de archivos y bloqueos de ramas.
- El ADE proporciona un canal unificado para terminales concurrentes, revisión de diffs y sincronización con gestores de tareas (GitHub, Linear).

---

## 2. Mapa Técnico de Componentes Reales

A continuación se detalla la estructura y componentes reales verificados en el repositorio [github.com/stablyai/orca](https://github.com/stablyai/orca):

```text
ORCA (Stably AI / Lovecast Inc.)
├── Core
│   ├── Electron Shell (Main & Renderer processes)
│   ├── Workspace Manager (Git repository detection & state tracking)
│   └── Config & Settings Store
├── Runtime
│   ├── node-pty / PTY Manager (Pseudoterminal spawner)
│   ├── WebGL Terminal Engine (xterm.js / Ghostty-class rendering)
│   └── orcad (Background Daemon for headless execution & session lifecycle)
├── Tools & Skills
│   ├── Bundled Skill Guides (`src/main/skills/`, `SKILL.md` format)
│   ├── Skill Bundle Manifest & Validator (integrity & hashing)
│   └── Browser Tool (Embedded Chromium with "Design Mode" inspector)
├── Planner / Coordinator
│   ├── Task Dispatcher (Decomposes tasks into sub-tasks)
│   └── Agent Session Authority (Routes prompts to target CLI agents)
├── Memory & State
│   ├── Zustand State Stores (Active sessions, tabs, worktrees)
│   └── Session Transcripts & PTY Replay Logs
├── Execution & Isolation
│   ├── Git Worktree Controller (`git worktree add`, `git worktree remove`)
│   └── Local CLI Process Spawner (Invokes user-installed coding agent CLIs)
├── Communication
│   ├── Runtime RPC (Internal JSON-RPC over IPC / sockets)
│   ├── Mobile Companion Gateway (iOS / Android push notifications & follow-up)
│   └── GitHub / Linear Issue & PR Synchronizer
└── External Dependencies
    ├── Git CLI (Host system)
    ├── Node.js / Electron runtime
    └── External Agent Subscriptions (Claude Code, OpenAI Codex, etc.)
```

```text
ADE (Agentic Development Environment Concept)
├── Core (Workspace isolation & Multi-Agent orchestration plane)
├── Runtime (Concurrent terminal virtualization & multiplexing)
├── Decision (Human-in-the-loop review, approval gates & diff selection)
├── Execution (Host shell processes inside temporary Git worktrees)
├── Tools (Design Mode / Screen capture / Task management connectors)
├── Storage (Ephemeral worktrees on disk, local Git history, state cache)
└── External Dependencies (Git, Agent CLIs, Remote SSH workers)
```

---

## 3. Relación entre ORCA y ADE

* **Complementariedad:** Orca es la implementación de referencia en software libre del paradigma ADE.
* **Dependencia:** No son dos productos separados en conflicto; Orca encarna las funciones del ADE.
* **Mecanismo de Integración Posible:**
  1. **A Nivel de Proceso / CLI:** Invocación del CLI `orca` (`out/cli/index.js`) para crear o inspeccionar worktrees.
  2. **A Nivel de Protocolo RPC:** Conexión con el daemon `orcad` mediante JSON-RPC.
  3. **A Nivel de Adapter Python (Recomendado para JESSYCA):** Un adapter local puro en Python (`core/orca_ade/adapter.py`) que adopte el contrato de especificación de tareas y aislamiento de worktrees sin arrastrar el binario de Electron innecesariamente al Core de JESSYCA.

---

## 4. Capability Mapping: ORCA vs ADE vs JESSYCA

| Capacidad | ORCA | ADE (Paradigma) | JESSYCA Equivalente | Utilidad para JESSYCA | Riesgo para JESSYCA |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Planning** | Despacho de tareas a agentes CLI | Descomposición en paralelo | **JDE + ARE** (DAG, análisis de impacto) | **BAJA:** JESSYCA ya posee su propio razonador causal y JDE. | **MEDIO:** Conflicto si Orca intenta tomar decisiones autónomas. |
| **Decision Authority** | Humano en el loop / review | Cockpit de aprobación humana | **JDE (Decision Engine)** | **NULA:** JDE es la autoridad única e inviolable de JESSYCA. | **CRÍTICO:** Violación del principio Single Authority si no se subordina. |
| **Tool Execution** | Skills (`SKILL.md`) + CLI PTY | Wrappers de herramientas | **JESSYCA Skills Registry + MCP** | **MEDIA:** Estandarización de `SKILL.md` es compatible. | **ALTO:** Orca ejecuta comandos arbitrarios en el shell del host. |
| **Memory** | Transcripciones PTY y estado UI | Logs de sesión temporales | **JESSYCA Memory System** (Short/Long term) | **BAJA:** Memoria de Orca es efímera para UI. | **BAJO:** Aislamiento de memoria requerido. |
| **Agent Orchestration** | Múltiples agentes CLI en paralelo | Flota de agentes paralelos | **JESSYCA Multi-Agent Core** | **ALTA (Conceptual):** El patrón de **Git Worktree Isolation** es muy valioso. | **MEDIO:** Sobrecarga de procesos y contención de CPU. |
| **Workflow** | Integración con GitHub PRs / Linear | Ciclo Task -> Worktree -> Merge | **JDE Workflow Orchestration** | **MEDIA:** Automatización de branching para tareas de codificación. | **MEDIO:** Manipulación del repositorio Git local. |
| **Code Execution** | Subprocesos directos vía `node-pty` | Shell del sistema sin sandbox | **JESSYCA Code Execution Skills** | **NULA:** JESSYCA requiere evaluación de riesgo previa. | **CRÍTICO:** Ejecución de código arbitrario sin sandboxing estricto. |
| **File Operations** | Escritura directa en worktree | Modificación física de archivos | **Files Skill / Workspace Manager** | **ALTA:** Aislamiento en ramas independientes evita ensuciar el checkout principal. | **MEDIO:** Riesgo de borrado accidental de branches si no se acota. |
| **Browser** | Chromium embebido con "Design Mode" | Inspección UI a prompt | **Browser Skill / Computer Use** | **MEDIA:** Captura de selectores y estilos para tareas frontend. | **MEDIO:** Consumo de RAM y posibles exploits web. |
| **MCP** | Soporte para herramientas externas | Conectividad estandarizada | **JESSYCA MCP Client / Server** | **ALTA:** Intercambio de herramientas mediante protocolo unificado. | **BAJO:** Estandarizado. |
| **Observability** | Telemetría UI y logs de terminal | Registro de eventos de agentes | **JESSYCA Observability Engine** | **MEDIA:** Captura de métricas de agentes externos. | **BAJO:** Fácil de canalizar a ErrorRecorder. |
| **Security** | Delegada al usuario humano | Confianza en los agentes | **RiskEngine + PermissionManager** | **NULA:** Orca no tiene un motor de riesgo proactivo intrínseco. | **CRÍTICO:** Requiere forzosamente que JDE/RiskEngine gobierne toda acción. |

---

## 5. Regla de No Duplicación

Al evaluar exhaustivamente las capacidades de ORCA + ADE frente a la arquitectura de JESSYCA PC:

1. **JDE vs Orca Coordinator:**
   * **Diagnóstico:** *ORCA introduce conflicto si actúa como autoridad de decisión.*
   * **Decisión:** El JDE de JESSYCA permanece como la **única autoridad de decisión**. Orca solo puede ser un **Capability Provider / Worker** que emite propuestas.

2. **Git Worktree Isolation:**
   * **Diagnóstico:** *ORCA/ADE añade capacidad real.*
   * **Decisión:** La técnica de aislar tareas de agentes en directorios `.git/worktrees/` paralelos resuelve limpiamente el problema de colisiones en el código de JESSYCA, permitiendo evaluar cambios de código en ramas efímeras antes de fusionarlos.

3. **Ejecución de Procesos (node-pty / shell directo):**
   * **Diagnóstico:** *ORCA no aporta valor seguro; duplica ejecución introduciendo vulnerabilidades.*
   * **Decisión:** No se permite a Orca invocar procesos del sistema arbitrarios directamente. Toda ejecución debe canalizarse a través de las Skills y el Security Pipeline de JESSYCA.

4. **Design Mode (Inspección UI):**
   * **Diagnóstico:** *ORCA/ADE mejora una capacidad existente.*
   * **Decisión:** La capacidad de inspeccionar elementos HTML/CSS y generar contexto visual para el prompt puede complementar el `ComputerUseAdapter` y las tareas de maquetación de JESSYCA en el futuro.

5. **Gestión de Memoria y Estado:**
   * **Diagnóstico:** *ORCA duplica una capacidad de forma inferior (solo estado de UI).*
   * **Decisión:** Se mantiene intacta la memoria productiva de JESSYCA. Ningún estado de Orca mutará la memoria del sistema.

---

## 6. Recomendación de Arquitectura para JESSYCA

Para integrar las virtudes de ORCA + ADE sin comprometer la seguridad ni la soberanía del JDE:

```text
[USER PROMPT]
      ↓
[JESSYCA CORE]
      ↓
[JDE (Decision Engine)] ────────── (AUTORIDAD ÚNICA: Decide si activar tarea agéntica)
      ↓
[RiskEngine & PermissionManager] ─ (Evalúa comandos y permisos de filesystem)
      ↓
[OrcaAdeAdapter (LAB / SHADOW)] ── (Genera propuesta estructurada de aislamiento)
      ↓
[Worktree Sandbox] ─────────────── (Aislamiento de Git Worktree controlado)
      ↓
[ExecutionVerifier] ────────────── (Verifica diffs, tests y artefactos)
      ↓
[JDE Receipt] ──────────────────── (Registra auditoría formal)
      ↓
[JESSYCA RESPONSE]
```

Orca jamás operará como entidad autónoma; se integrará como un **Proveedor de Aislamiento y Paralelismo en Worktrees** subordinado en todo momento al JDE.
