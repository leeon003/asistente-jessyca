# CONTROLLED AUTONOMY — JESSYCA 3.0 (FASE 15)

## 1. Arquitectura de Autonomía Controlada y Tareas Persistentes

El módulo de Autonomía Controlada (`core/autonomy/autonomous_task_manager.py` y `autonomous_task_models.py`) permite la ejecución segura de tareas programadas multi-step mediante la orquestación coordinada de `Scheduler` + `Agent System`:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Programación / Disparo                   │
│           (Interval / Cron / Startup / Evento)              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   AutonomousTaskManager                     │
│         (Ciclo de Vida: PENDING -> RUNNING -> ...)          │
│       • Cancelación inmediata (CANCELLED)                   │
│       • Pausa / Reanudación (PAUSED / PENDING)              │
│       • Safe Recovery on Startup                            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   Asignación al Agente                      │
│             (DesktopAgent / SystemAgent / ...)              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   ControlledAgentLoop                       │
│    (OBSERVE -> ANALYZE -> REPORT -> STOP | AgentBudget)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      SecurityPipeline                       │
│  (Evaluación per-action: Tool, Param, Risk, EmergencyStop)  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Invariantes de Seguridad Inmutables

1. **`SCHEDULER != AUTHORIZATION`**:
   - Una tarea programada o recurrente NO concede permisos adicionales ni eleva privilegios.
2. **`TASK != AUTHORIZATION`**:
   - Cada acción individual dentro del loop del agente pasa forzosamente por la validación de seguridad (`SecurityPipeline` y `AutonomyPolicy`).
3. **`AGENT NO MODIFICA SU AUTONOMÍA`**:
   - Ningún LLM, agente o tarea puede cambiar su nivel de autonomía asignado ni sobrepasar su `risk_ceiling`.
4. **Presupuesto Acotado (`AgentBudget`)**:
   - Todo trabajo autónomo posee un techo estricto de pasos (`max_steps`), tiempo (`max_time_seconds`), acciones (`max_actions`) y reintentos. Al excederse $\rightarrow$ `STOP`.
5. **Aislamiento y Pausa Preventiva en Reinicio (`Safe Startup Recovery`)**:
   - Si el sistema se reinicia, las tareas en ejecución se recuperan de forma segura y las tareas con riesgo `DANGEROUS` o `CRITICAL` se colocan automáticamente en `PAUSED` requiriendo confirmación explícita.
6. **Prevalencia de Parada de Emergencia (`EmergencyStop`)**:
   - Cualquier activación de `EmergencyStop` cancela y aborta de inmediato todas las tareas autónomas activas.

---

## 3. Estados Formales del Ciclo de Vida (`AutonomousTaskStatus`)

- `PENDING`: Esperando turno de ejecución programada.
- `RUNNING`: En ejecución activa dentro de `ControlledAgentLoop`.
- `PAUSED`: Pausada por usuario o por política preventiva.
- `COMPLETED`: Tarea finalizada exitosamente.
- `FAILED`: Tarea detenida por error o agotamiento de presupuesto.
- `CANCELLED`: Cancelada permanentemente.
- `EXPIRED`: Tarea caducada por tiempo de vida superado.

---

## 4. Resultados de Verificación

| Métrica / Suite | Pruebas | Resultado |
|:---|:---:|:---:|
| **`pytest tests/autonomy/test_controlled_autonomy.py`** | 7 pruebas (tarea simple, periódica, cancelación, pausa/reanudación, recovery con aislamiento de riesgo, agotamiento de presupuesto, security denial, emergency stop) | ✅ **7 / 7 PASS** |
| **`pytest tests/autonomy/`** | 167 pruebas de autonomía y límites de seguridad | ✅ **167 / 167 PASS** |
| **`ruff check`** | `core/autonomy/`, `tests/autonomy/` | ✅ **All checks passed!** |
