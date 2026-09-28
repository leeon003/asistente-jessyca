# GUÍA DE INTEGRACIÓN Y ESPECIFICACIÓN: ORCA + ADE

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 3 — Final Certification & Controlled Production Activation  
**Estado:** `ACTIVE` (Gobernado bajo JDE — 7 Capacidades Certificadas)  
**Autoridad:** JESSYCA Decision Engine (JDE)  
**Fecha:** Septiembre 2026  

---

## 1. Overview y Concepto

Este documento define la arquitectura, contratos formales y directrices operativas para ejecutar **ORCA + ADE** bajo integración gobernada (**CONTROLLED**) en JESSYCA PC.

- **ORCA:** Orquestador de escritorio de código abierto desarrollado por Lovecast Inc. / Stably AI ([github.com/stablyai/orca](https://github.com/stablyai/orca)).
- **ADE (Agentic Development Environment):** Paradigma de desarrollo para supervisar flotas de agentes concurrentes aislados mediante **Git Worktrees**.

---

## 2. Capacidades Certificadas en Modo CONTROLLED

En `core/jde/capabilities.py`, las siguientes 7 capacidades se encuentran habilitadas exclusivamente bajo gobernanza del JDE:

1. `agent_orchestration.task_creation`: Generación formal del contrato tipado `OrcaTaskContract`.
2. `agent_orchestration.worktree_isolation`: Aislamiento físico de workspaces mediante `git worktree add`.
3. `agent_orchestration.parallel_execution`: Coordinación paralela de hasta 10 agentes simultáneos.
4. `agent_orchestration.agent_lifecycle`: Máquina de estados estricta `AgentLifecycle`.
5. `agent_orchestration.result_collection`: Recolección estructurada del contrato `OrcaResultContract`.
6. `agent_orchestration.failure_isolation`: Aislamiento de colisiones y prevención de corrupción de rama base.
7. `agent_orchestration.review`: Puerta de aprobación obligatoria (Review Gate).

---

## 3. Arquitectura y Cadena Inviolable de Autoridad

```text
USER PROMPT
  ↓
JESSYCA CORE
  ↓
JDE (Decision Engine) ────────── (Single Authority: ALLOW / DENY)
  ↓
RiskEngine ───────────────────── (Bloqueo de tareas CRITICAL)
  ↓
PermissionManager ────────────── (Allowlist de permisos de repositorio)
  ↓
IdempotencyGuard ─────────────── (Fingerprint SHA-256 de tarea)
  ↓
OrcaGovernedOrchestrator ─────── (Máquina de estados AgentLifecycle)
  ↓
Isolated Git Worktree ────────── (Espacio de trabajo confinado en rama efímera)
  ↓
ExecutionVerifier ────────────── (Inspección física y anti falso-éxito)
  ↓
Review Gate ──────────────────── (Aprobación humana/JDE previa a merge)
  ↓
JDE Receipt ──────────────────── (Recibo oficial con telemetría inmutable)
  ↓
JESSYCA RESPONSE
```

### Regla Fundamental: ORCA ≠ AUTHORITY
* Orca y ADE **carecen de autoridad decisoria**.
* Todo comando pasa por `CommandSecurityGuard` (allowlist cerrada de `git`, `pytest`, `python`).
* La red está denegada por defecto (`NETWORK = DENY`).
* El agente **no puede autoaprobar sus parches de código**.

---

## 4. Ciclo de Vida del Agente (AgentLifecycle)

```text
CREATED ──(JDE ALLOW)──> AUTHORIZED ──> STARTING ──> RUNNING ──> WAITING_REVIEW ──(Approve)──> COMPLETED
   │                                                     │              │
   └──(JDE DENY)──> DENIED                               ├──(Crash)─────┴──> FAILED
                                                         ├──(Timeout)───────> TIMEOUT
                                                         └──(Verification)──> VERIFICATION_FAILED
```

Saltos ilegales (ej. `CREATED -> COMPLETED`) están bloqueados por código arrojando `ValueError`.

---

## 5. Idempotencia y Reutilización Segura

Cada tarea computa un fingerprint SHA-256:
$$\text{Fingerprint} = \text{SHA-256}(\text{objective} + \text{workspace} + \text{allowed\_actions} + \text{forbidden\_actions} + \text{timeout} + \text{requires\_review})$$

Tareas idénticas devuelven instantáneamente `CACHE_HIT` con `duration_ms < 0.2 ms` sin instanciar nuevos procesos.

---

## 6. Procedimientos de Rollback y Control de Modos

Para revertir de forma inmediata la integración sin reiniciar el sistema:
```python
from core.orca_ade import OrcaAdeAdapter, OrcaAdeMode

adapter = OrcaAdeAdapter()

# Reversión a modo Sombra (cero efectos)
adapter.set_mode(OrcaAdeMode.SHADOW)

# Reversión a modo Laboratorio aislado
adapter.set_mode(OrcaAdeMode.LAB)

# Apagado total inmediato (Kill-Switch)
adapter.set_mode(OrcaAdeMode.OFF)
```
Para activar `OrcaAdeMode.ACTIVE`, se requiere previamente la certificación formal mediante `adapter.set_certified(True)`.

---

## 7. Criterios de Certificación de Producción (Fase 3 — SUPERADA)

- [x] Autoridad única del JDE demostrada en ALLOW, DENY, CONFLICT y tamper seal.
- [x] Aislamiento en Git Worktrees reales comprobado (CERT-A, B, C, D).
- [x] Detección de colisiones validada sin corrupción ni pérdida de datos.
- [x] Máquina de estados y Review Gate con prohibición de auto-aprobación del agente.
- [x] Allowlist de comandos e inmunidad ante inyecciones (&&, ;, |, etc.).
- [x] Bloqueo total de red (`NETWORK = DENY`) con excepción exclusiva a loopback ligado a decisión JDE.
- [x] Redacción profunda de secretos auditada en payloads, logs y reportes.
- [x] Suite de regresión consolidada (412/412 tests) pasando al 100%.
- [x] 15/15 Escenarios E2E finales superados con 0 efectos laterales no auditados.
- [x] Modo `ACTIVE` formalmente activado bajo estricta gobernanza JDE.
