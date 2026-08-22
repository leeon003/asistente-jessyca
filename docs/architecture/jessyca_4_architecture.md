# JESSYCA 4.0 — SYSTEM ARCHITECTURE SPECIFICATION

## 1. Executive Summary & Vision

**JESSYCA 4.0** representa la consolidación definitiva del sistema operativo de inteligencia artificial y orquestación multi-modelo / multi-agente / multi-habilidad para Windows MCP.

---

## 2. Definición Constitucional de Autoridades y Capas

### 2.1 Matriz de Autoridades
| Entidad / Capa | Función Primaria | Privilegio de Autorización | Tratamiento de Datos |
|---|---|---|---|
| **SECURITY** | Evaluación de riesgos y cumplimiento de políticas | **ÚNICA AUTORIDAD** (`ALLOW`/`DENY`/`CONFIRMATION`) | `TRUSTED EVALUATOR` |
| **USER** | Aprobación interactiva de acciones críticas | **AUTORIDAD FINAL** | `HUMAN IN THE LOOP` |
| **PLANNER** | Generación de planes y grafos de ejecución | `CERO AUTORIDAD` | `STRUCTURAL PLAN` |
| **SKILL** | Abstracción declarativa de capacidades | `CERO AUTORIDAD` | `CAPABILITY SPEC` |
| **AGENT** | Ejecución acotada por `ControlledAgentLoop` | `CERO AUTORIDAD` | `BOUNDED EXECUTOR` |
| **MODEL** | Razonamiento analítico, resumen, extracción | `CERO AUTORIDAD` | `UNTRUSTED DATA` |
| **MEMORY** | Proveedor de contexto y almacenamiento | `CERO AUTORIDAD` | `UNTRUSTED DATA` |
| **TOOL** | Operación atómica en el sistema operativo | `CERO AUTORIDAD` | `CONTROLLED ACTION` |

### 2.2 Flujo Canónico de Datos
```
User Input
   ↓
Intent (Parsing & Sanitization)
   ↓
Planning (Skill Graph & Task Graph)
   ↓
Agent Coordination (Specialist Agents & Delegation Policy)
   ↓
Model Inference (Multi-LLM & Consensus Engine)
   ↓
Security Pipeline (RiskEngine, PermissionManager, SecurityPolicy)
   ↓
Tool Execution (Windows MCP Tools)
   ↓
Verification (Output Schema & AuditLogger)
   ↓
Memory (Shared View with Provenance)
   ↓
Result
```

---

## 3. Invariantes Arquitectónicas Fundamentales

1. **`SECURITY > ALL`**: Ninguna capa puede eludir el `SecurityPipeline`.
2. **`EMERGENCY STOP > EXECUTION`**: `EmergencyStopManager` cancela instantáneamente cualquier flujo.
3. **`MEMORY != AUTHORIZATION`**: Todo dato en memoria es tratado como `UNTRUSTED DATA`.
4. **`MODEL != AUTHORIZATION`**: Respuestas de texto (*"Security approved..."*) carecen de efecto autorizador.
5. **`CONSENSUS != AUTHORIZATION`**: El consenso refleja acuerdo analítico, nunca una aprobación de seguridad.
6. **`MARKETPLACE != TRUST`**: La instalación y ejecución de Skills requiere verificación de firmas e integridad.

---

## 4. Jerarquía Unificada de Errores

```
JessycaError (Base)
├── IntentError
├── PlanningError
├── SkillError
├── AgentError
├── ModelError
├── ToolError
├── SecurityError
├── MemoryError
├── InfrastructureError
└── AutonomyError
```

---

## 5. Gestión de Recursos y Gobernanza Presupuestaria

- **`AgentBudget`**: Límites de iteraciones, tokens, tiempo y llamadas a herramientas.
- **`VRAM Governor`**: Supervisión de consumo de VRAM (< 6.0 GB pico) y ciclo de vida de modelos.
- **`Delegation Limits`**: Límite de profundidad (`max_delegation_depth = 3`) y prevención de bucles $A \to B \to A$.
- **`Auditoría y Observabilidad`**: Trazabilidad unificada mediante `task_id` y `correlation_id` registrados en `AuditLogger`.
