# JESSYCA BRAIN 1.0 — FASE 5: APRENDIZAJE PROCEDIMENTAL (PROCEDURE LEARNING ENGINE)

## 1. RESUMEN EJECUTIVO DE LA FASE 5

La **Fase 5 de JESSYCA BRAIN 1.0** implementa el subsistema de **Aprendizaje Procedimental Continuo (`ProcedureLearningEngine`)**, dotando a JESSYCA de la capacidad cognitiva para:
1. Aprender procedimientos estructurados, acotados y reutilizables a partir de **experiencias exitosas verificadas**.
2. Aprender por **demostración supervisada ("JESSYCA, aprende este procedimiento")**, con aislamiento de ventanas autorizadas, sanitización activa de contraseñas/secretos y captura basada en identificadores de accesibilidad (UIA).
3. Aprender de **errores de interfaz y fallos de ejecución**, adaptando reintentos, tiempos de espera y estrategias de re-observación de ventanas sin alterar el código fuente de la aplicación.
4. Validar procedimientos mediante pruebas independientes supervisadas en un ciclo de vida formal:
   $$\text{CANDIDATE} \longrightarrow \text{TESTING} \longrightarrow \text{VALIDATED} \longrightarrow \text{DEPRECATED}$$
5. Reutilizar inteligentemente procedimientos validados mediante sustitución de parámetros dinámicos (**Smart Parameter Adaptation**), sustituyendo plantillas `{{param}}` por los valores reales de la solicitud del usuario.
6. Preservar la gobernanza de seguridad total (JDE, `RiskEngine`, `PermissionManager`, `SessionExecutionLock` y Parada de Emergencia).

---

## 2. ARQUITECTURA DEL MOTOR DE APRENDIZAJE PROCEDIMENTAL

`ProcedureLearningEngine` se ubica en `core/cognitive_brain/procedure_learning_engine.py` y se integra de forma directa con `JessycaBrain` y los contratos establecidos en la Fase 1:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             JESSYCA BRAIN 1.0                               │
│                                                                             │
│  Usuario ──> ReasoningEngine ──> MemoryEngine ──> PlannerEngine             │
│                                        │                │                   │
│                                        ▼                ▼                   │
│                             ProceduralMemory ◄─── ProcedureLearningEngine   │
│                               (SQLite WAL)              │                   │
│                                                         │                   │
│  Respuesta <── MemoryEngine <── ExecutionVerifier <── UnifiedDesktop        │
│                     ▲                                    Controller         │
│                     │                                   (Native / CUA)      │
│                     └────── learn_from_experience ──────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Modelo de Datos del Procedimiento (`LearnedProcedure`)
Reutiliza el contrato formal de `core/cognitive_brain/contracts.py`:
- `procedure_id`: Identificador único determinista (`proc-xxxxxxxx`).
- `name`: Nombre descriptivo legible (ej. `desktop_edit:notepad_notes`, `informe_ia:generar_reporte`).
- `description`: Explicación detallada de lo que realiza la secuencia.
- `associated_intent`: Intención semántica vinculada.
- `required_applications`: Lista de ejecutables de Windows requeridos (`notepad.exe`, `calc.exe`, etc.).
- `authorized_tools`: Herramientas permitidas con evaluación previa de riesgo.
- `input_parameters`: Esquema tipado de parámetros dinámicos identificados (`topic`, `filename`, `text`).
- `preconditions`: Condiciones previas verificables antes de ejecutar.
- `steps`: Pasos canónicos con marcadores `{{param}}` para permitir generalización.
- `success_conditions`: Criterios de verificación observables de éxito.
- `error_conditions`: Patrones conocidos de fallo para detección temprana.
- `validation_evidence`: Evidencias criptográficas/observables de validación.
- `version`: Entero incremental que preserva la evolución del procedimiento.
- `state`: Estado del ciclo de vida (`ProcedureLifecycleState`).
- `approval_status`: Estado de aprobación (`PROPOSED`, `APPROVED`, `REJECTED`).
- `last_validated_at`: Timestamp de la última verificación independiente exitosa.
- `success_count` / `failure_count`: Telemetría empírica de confiabilidad.

---

## 3. MECANISMOS DE APRENDIZAJE IMPLEMENTADOS

### 3.1 Aprendizaje por Experiencia (`learn_from_experience`)
- Se activa tras la finalización exitosa de cualquier plan ejecutado por `JessycaBrain`.
- Analiza las acciones ejecutadas y filtra tareas triviales o puramente conversacionales.
- Generaliza parámetros específicos (rutas de archivos, textos mecanografiados, consultas) reemplazándolos por marcadores de plantilla (`{{filename}}`, `{{text}}`, `{{query}}`).
- Registra el procedimiento en `ProceduralMemory` en estado `CANDIDATE`.

### 3.2 Aprendizaje por Demostración (`DemonstrationSession`)
- Iniciado mediante `start_demonstration(name, intent, target_applications)`.
- Requiere confirmación explícita previa del usuario (`user_confirmed=True`).
- **Sanitización de Privacidad Activa**: Todo texto ingresado es inspeccionado mediante filtros de expresiones regulares contra contraseñas, tokens y números de tarjeta de crédito, sustituyéndolos por `[REDACTED_SECRET]` o `[REDACTED_CARD]`.
- Permite pausar (`pause_demonstration`) y reanudar (`resume_demonstration`).
- Al invocar `stop_demonstration`, compila las acciones observadas en pasos estructurados, aplica correcciones del usuario y genera un `LearnedProcedure` en estado `CANDIDATE`.

### 3.3 Aprendizaje de Errores y Adaptación Heurística (`learn_from_failure`)
- Cuando un paso falla durante la ejecución física o la validación, `learn_from_failure` analiza la evidencia del error.
- Incrementa `failure_count` y registra el incidente en `modification_history`.
- Inyecta adaptaciones seguras: incremento de reintentos (`retry_limit`), ajuste de tiempos de espera (`timeout_seconds`) y estrategias de re-observación fresca de coordenadas (`reobserve_window_bounds`).
- Si la tasa de fallos es recurrente ($\ge 2$ fallos), degrada automáticamente el procedimiento de `VALIDATED` a `TESTING` para impedir falsos éxitos en producción.

### 3.4 Reutilización Inteligente (`adapt_procedure_to_plan`)
- Antes de planificar desde cero, `JessycaBrain` consulta `ProceduralMemory` buscando procedimientos `VALIDATED` coincidentes.
- Si existe una coincidencia, `adapt_procedure_to_plan` extrae las entidades del usuario y sustituye las plantillas `{{param}}` en los pasos del procedimiento.
- **Regla de Oro de Seguridad**: Un procedimiento en estado `CANDIDATE` o `TESTING` lanza `PermissionError` y es rechazado para ejecución automática.

---

## 4. PERSISTENCIA EN MEMORIA PROCEDIMENTAL

La persistencia se gestiona a través de `ProceduralMemory` en `data/memory_brain.db` con soporte para WAL (`Write-Ahead Logging`), transacciones atómicas y migración no destructiva de esquemas. La persistencia sobrevive completamente a reinicios del proceso.
