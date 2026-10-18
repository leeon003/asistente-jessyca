# JESSYCA BRAIN 1.0 — FASE 5: ARQUITECTURA DE SEGURIDAD Y CONTROL DE APRENDIZAJE

**Fecha:** 16 de Octubre de 2026  
**Subsistema:** `core/cognitive_brain/procedure_learning_engine.py`  
**Políticas Activas:** JDE (Jessyca Deterministic Execution), `RiskEngine`, `PermissionManager`, `ExecutionVerifier`

---

## 1. PRINCIPIOS DE SEGURIDAD DEL APRENDIZAJE PROCEDIMENTAL

El diseño del motor de aprendizaje `ProcedureLearningEngine` se rige por el principio de **Mínimo Privilegio y Cero Confianza Implícita**. Ningún procedimiento aprendido, independientemente de cuántas veces haya sido ejecutado, puede auto-asignarse privilegios o eludir las barreras de control de JESSYCA.

```
                                 ┌────────────────────────────────┐
                                 │   Usuario / Demostración /     │
                                 │       Experiencia Pasada       │
                                 └───────────────┬────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ CAPA DE SEGURIDAD Y GOBERNANZA PROCEDIMENTAL                                                    │
│                                                                                                 │
│  1. Sanitización de Privacidad  ──> Filtra contraseñas, tokens y tarjetas antes de guardar      │
│  2. Barrera de Ciclo de Vida    ──> Bloquea ejecución automática de CANDIDATE y TESTING         │
│  3. Verificación de Permisos    ──> Evalúa permisos vigentes en CADA ejecución (sin elevación) │
│  4. Aislamiento de Código       ──> PROHIBIDO auto-modificar scripts Python del sistema         │
│  5. Cancelación Activa & Stop   ──> Detiene la ejecución en tiempo real y salva checkpoint     │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                                                 ▼
                                ┌─────────────────────────────────┐
                                │   Ejecución Segura en Windows   │
                                └─────────────────────────────────┘
```

---

## 2. BARRERAS Y CONTROLES ESPECÍFICOS

### 2.1 Prohibición Estricta de Elevación de Privilegios
- Un procedimiento aprendido solo puede ejecutar las herramientas autorizadas contenidas en su declaración (`authorized_tools`).
- Si una tarea requiere una herramienta con nivel de riesgo `HIGH` o `CRITICAL` (por ejemplo, eliminación de carpetas, modificación del registro de Windows o instalación de software), el procedimiento **no puede omitir la solicitud de confirmación del propietario**.
- El `PermissionManager` evalúa los permisos en el instante exacto de la ejecución física, no en el momento en que se aprendió la tarea.

### 2.2 Bloqueo de Procedimientos No Validados
- Todo procedimiento recién aprendido por experiencia o demostración nace con el estado `ProcedureLifecycleState.CANDIDATE`.
- La función `adapt_procedure_to_plan` evalúa de forma obligatoria:
  ```python
  if procedure.state != ProcedureLifecycleState.VALIDATED:
      raise PermissionError(
          f"Procedimiento {procedure.procedure_id} no está en estado VALIDATED "
          f"(estado actual: {procedure.state.value}). Ejecución automática bloqueada."
      )
  ```
- No es posible la ejecución desatendida de procedimientos candidatos en el entorno de producción del usuario.

### 2.3 Sanitización Activa de Datos Sensibles en Demostraciones
Durante el modo "JESSYCA, aprende este procedimiento", el sistema graba eventos de teclado y ventana. Para evitar la exfiltración o persistencia de secretos:
1. **Detección de Patrones de Contraseña y Tokens:**
   - Palabras clave como `password:`, `secret:`, `token:`, `bearer:` son neutralizadas.
   - Patrones de tokens de API (`ghp_`, `sk-`, `ey...`) son sustituidos por `[REDACTED_SECRET]`.
2. **Detección de Información Financiera:**
   - Números de tarjetas de crédito (13 a 19 dígitos formateados con o sin guiones) son sustituidos por `[REDACTED_CARD]`.
3. **Aislamiento de Ventanas:**
   - Solo se capturan acciones dirigidas a la lista explícita de aplicaciones autorizadas (`target_applications`). Las interacciones fuera de esas ventanas son descartadas de inmediato.

### 2.4 Inmunidad del Código Fuente ante Errores
- Cuando un procedimiento falla, el motor `learn_from_failure`:
  - **NUNCA modifica código Python ni scripts del sistema.**
  - Solo ajusta metadatos heurísticos de ejecución dentro de los límites seguros:
    - Incremento de reintentos (`retry_limit`: máximo 3).
    - Tiempos de espera (`timeout_seconds`: máximo 30s).
    - Bandera de re-observación de geometría de ventanas (`reobserve_window_bounds=True`).
- Si los fallos continúan tras la adaptación, el procedimiento es **degradado a `TESTING`**, requiriendo intervención y supervisión del propietario.

### 2.5 Rechazo de Procedimientos Procedentes de Fuentes Externas No Confiables
- Contenidos extraídos de páginas web, correos electrónicos o documentos externos procesados por JESSYCA se tratan estrictamente como **datos inertes**, nunca como instrucciones ejecutables o procedimientos aprendidos.
- No existe ningún mecanismo que convierta texto web en un `LearnedProcedure` sin una sesión formal de supervisión y validación local.

### 2.6 Parada de Emergencia y Cancelación Activa Mid-Task
- `JessycaBrain` mantiene un token de cancelación activo (`active_cancellation_token`).
- Durante la ejecución de un plan de múltiples pasos, el motor comprueba el estado del token entre cada paso:
  - Si el usuario o el sistema solicitan la parada, se interrumpe de inmediato la secuencia de automatización (`ExecutionCancelledByUser`).
  - Se registra el checkpoint en el `TaskJournal` con el último paso verificado.
  - La reanudación posterior verifica el estado real para evitar repetir acciones irreversibles.
