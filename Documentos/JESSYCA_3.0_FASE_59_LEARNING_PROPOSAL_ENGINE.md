# JESSYCA 3.0 — FASE 59: LEARNING PROPOSAL ENGINE
## JESSYCA EXPERIENCE & LEARNING ENGINE

**Fecha de Implementación y Certificación:** 22 de Agosto de 2026  
**Estado:** CERTIFICADO Y VALIDADO (100% Tests Aprobados — 2,076/2,076)

---

## 1. OBJETIVO Y ALCANCE

La **Fase 59** implementa el **Learning Proposal Engine**, el tercer pilar del **JESSYCA EXPERIENCE & LEARNING ENGINE**, completando el flujo:

$$\text{Experience} \xrightarrow{\text{Fase 57}} \text{Analysis} \xrightarrow{\text{Fase 58}} \text{Learning Proposal} \xrightarrow{\text{Fase 59}}$$

### Invariantes Fundamentales de Gobernanza y Seguridad:
1. **Una propuesta NO es una modificación:** No posee permisos de ejecución en esta fase ni se auto-despliega de forma autónoma.
2. **Máquina de Estados Estricta:** Regula el ciclo de vida determinista:
   - `DRAFT` $\to$ `VALIDATED` $\to$ `SIMULATION_PENDING` $\to$ `READY_FOR_EVALUATION` $\to$ `APPROVED` $\to$ `DEPLOYED` $\to$ `ROLLED_BACK`
   - Rutas de rechazo: `DRAFT | VALIDATED | READY_FOR_EVALUATION | APPROVED` $\to$ `REJECTED`
   - Rutas de simulación: `SIMULATION_PENDING` $\to$ `SIMULATION_FAILED` $\to$ `SIMULATION_PENDING`
   - Expiración: Cualquier estado no terminal $\to$ `EXPIRED`
   - Bloqueo tajante de saltos arbitrarios (ej. `DRAFT` $\to$ `DEPLOYED`).
3. **Protección Absoluta de Perímetros de Seguridad:** Rechazo automático de cualquier propuesta que mencione o intente afectar:
   - `security_policy`, `permission_manager`, `confirmation_manager`, `audit_logger`, `credential_handling`, `secret_storage`, `authentication`, `sandbox_boundaries`, `execution_boundary`, `mcp_security_boundaries`, `risk_engine`, `emergency_stop`.
4. **Completitud y Evidencia Auditable:** Cada propuesta fundamenta el problema, la evidencia acumulada, las ocurrencias, el comportamiento actual, la mejora propuesta, el beneficio esperado, el nivel de riesgo y las pruebas requeridas.

---

## 2. ARQUITECTURA DEL PAQUETE `core/learning/`

```text
core/learning/
├── __init__.py               # Exportaciones unificadas del módulo
├── proposal_models.py        # Modelos Pydantic v2 (LearningProposal, ProposalStatus, etc.)
├── proposal_validator.py     # Validador de seguridad, completitud y máquina de estados
├── simulator.py              # Protocolo IProposalSimulator y simulador controlado
├── proposal_store.py         # Almacenes persistentes InMemory y SQLite con WAL
└── proposal_engine.py        # Motor de generación y gestión del ciclo de vida
```

---

## 3. MODELOS Y MÁQUINA DE ESTADOS (`proposal_models.py` & `proposal_validator.py`)

### Estados Formales (`ProposalStatus`)
- `DRAFT`: Propuesta recién generada pendiente de validación técnica.
- `VALIDATED`: Propuesta verificada que cumple con los requisitos de evidencia y seguridad.
- `SIMULATION_PENDING`: En cola para simulación en entorno seguro.
- `READY_FOR_EVALUATION`: Simulación aprobada lista para evaluación humana/supervisada.
- `APPROVED`: Propuesta aprobada formalmente.
- `DEPLOYED`: Propuesta desplegada (reservado para fases futuras).
- `REJECTED`: Propuesta desestimada con motivo registrado.
- `SIMULATION_FAILED`: Simulación con regresiones o fallos detectados.
- `ROLLED_BACK`: Reversión técnica documentada.
- `EXPIRED`: Propuesta obsoleta por vencimiento temporal.

### Categorías Soportadas (`ProposalCategory`)
- `STT`, `INTENT`, `CLARIFICATION`, `TOOL`, `BROWSER`, `DESKTOP`, `PERFORMANCE`, `MEMORY`, `PERSONALIZATION`, `UX`.

---

## 4. MOTOR GENERADOR Y SIMULADOR (`proposal_engine.py` & `simulator.py`)

- **`LearningProposalEngine`**: Transforma patrones del `ExperienceAnalyzer` en propuestas estructuradas:
  - `STTPattern` $\to$ Propuestas de pistas de vocabulario contextual para nombres de apps y comandos de Windows.
  - `FailurePattern` $\to$ Propuestas de validación previa de precondiciones y reintentos deterministas.
  - `LatencyPattern` $\to$ Propuestas de optimización de pipelines y caché de resolución.
  - `CorrectionPattern` $\to$ Propuestas de reordenamiento de prioridades de slots contextuales.
  - `IntentPattern` $\to$ Propuestas de refinamiento de plantillas de desambiguación.
- **`ProposalSimulator`**: Interfaz de evaluación controlada previa a la aprobación formal.

---

## 5. RESULTADOS DE LA CERTIFICACIÓN

### Batería de Pruebas (`pytest`)
- **Suite de Learning Proposal Engine (`tests/learning/`):** 21/21 tests aprobados (100%).
- **Suites de Experience Logger & Analyzer (`tests/experience/`):** 26/26 tests aprobados (100%).
- **Suite de Regresión Global del Sistema:** **2,076/2,076 tests aprobados (100%)** en 191s.
- **Análisis Estático de Tipos (`mypy`):** 0 errores en `core/learning/` y `core/experience/`.
- **Linter (`ruff`):** 100% de cumplimiento en estilo y formateo.

---

## 6. CONCLUSIÓN

La Fase 59 concluye exitosamente la trilogía fundamental del **JESSYCA EXPERIENCE & LEARNING ENGINE** (Fases 57, 58 y 59), dotando al asistente de un mecanismo de introspección empírica, diagnóstico y formulación de mejoras estructuradas bajo un régimen de seguridad y gobernanza inquebrantable.
