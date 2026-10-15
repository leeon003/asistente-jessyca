# ETAPA 1: ESTADO ACTUAL DE CUA EN JESSYCA 3.0

**Fecha de evaluación:** 2026-10-14  
**Rama:** `eval/gui-agents`  
**Repositorio:** `leeon003/asistente-jessyca`  
**Criterio de Aceptación (PASS):** Cada afirmación cita el archivo y la línea exacta del código fuente.

---

## 1. DÓNDE SE USA CUA EN EL CÓDIGO

CUA (Computer Use Agent) se encuentra implementado actualmente en el repositorio a través de tres capas principales:

1. **Capa de Habilidad (Skill Contract):**
   - **Archivo:** [`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L34-L63)
   - **Clase:** `WindowsComputerUseSkill(BaseSkill)` (Líneas 34–63).
   - **Registro:** Identificador de manifiesto `windows.computer_use` (Líneas 39, 51), versión 1.0.0, clasificado con nivel de riesgo 3 / `SecurityLevel.HIGH` (Líneas 48, 58, 62).
   - **Interfaz:** Implementa tanto `ejecutar(parametros)` (Líneas 72–181) como la interfaz moderna del Skill Framework `execute(context: SkillContext) -> SkillResult` (Líneas 183–198).

2. **Capa de Adaptador de Integración (Integration Adapter):**
   - **Archivo:** [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L48-L63)
   - **Clase:** `ComputerUseAdapter(IntegrationAdapter)` (Líneas 48–63).
   - **Registro en el Hub:** Auto-registrado como `windows_computer_use` en [`core/integration/hub.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/hub.py#L128).
   - **Capacidades registradas:** Registra 5 capacidades auditadas en [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L64-L140):
     - `computer_use.observe_desktop` (Líneas 68–78)
     - `computer_use.mouse_interact` (Líneas 82–96)
     - `computer_use.keyboard_type` (Líneas 100–112)
     - `computer_use.window_control` (Líneas 116–126)
     - `computer_use.perceive_and_act` (Líneas 130–139)

3. **Capa de Ejecución y Accesibilidad UI Automation (UIA):**
   - **Archivos:** [`tools/desktop/ui_backend.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/ui_backend.py#L25-L60), [`tools/desktop/executors.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/executors.py#L30-L90), [`tools/desktop/action_verifier.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/action_verifier.py#L20-L80).
   - Proporciona inspección semántica de controles de accesibilidad (`AutomationId`, `Name`, `ClassName`) e interacción física complementaria sobre ventanas Win32.

---

## 2. CON QUÉ MODELO SE EJECUTA

1. **Modelo de Visión Multimodal (Percepción de Pantalla):**
   - **Modelo configurado:** `qwen3-vl:4b` vía Ollama local.
   - **Archivo:** [`core/vision/vision_provider.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/vision/vision_provider.py#L23), línea 23:
     ```python
     DEFAULT_VISION_MODEL = "qwen3-vl:4b"
     ```
   - **Implementación:** [`core/vision/ollama_vision_provider.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/vision/ollama_vision_provider.py#L40-L130). Envía la captura en Base64 al backend local de Ollama a través de `InferenceRequest` con temperatura 0.1 (Líneas 72–78).

2. **Modelos de Orquestación y Razonamiento del Asistente:**
   - **Modelo de producción por defecto:** `gemma4:e4b` (ejecución rápida local y baja latencia).
     - **Cita:** [`tools/run_shadow_traffic_validation.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/run_shadow_traffic_validation.py#L175): `PRODUCTION_MODEL = "gemma4:e4b"`.
     - **Cita:** [`tests/router/test_phase5_controlled_routing.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/router/test_phase5_controlled_routing.py#L74-L76): `assert exec_model == "gemma4:e4b"`.
   - **Modelo secundario / fallback:** `llama3.1:latest` (`llama3.1`).
     - **Cita:** [`CUA_EVALUACION.md`](file:///d:/JESSYCA%203.0/asistente-jessyca/CUA_EVALUACION.md#L41-L45) y [`tests/security/test_fase_11_multi_agent_security_certification.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/security/test_fase_11_multi_agent_security_certification.py#L199).
   - **Observación de uso real:** En el 95% de los casos interactivos de escritorio, Jessyca no realiza inferencia por visión completa de pantalla debido a la latencia (~3,500 ms) y utiliza en su lugar el backend determinista de UI Automation (~10 ms), reservando el modelo de visión solo para casos sin jerarquía accesible ([`Documentos/AUDITORIA_COMPUTER_USE_78.md`](file:///d:/JESSYCA%203.0/asistente-jessyca/Documentos/AUDITORIA_COMPUTER_USE_78.md#L170-L176)).

---

## 3. QUÉ ACCIONES PERMITE

El adaptador y la skill exponen las siguientes acciones físicas y de telemetría:

1. **Observación y Telemetría:**
   - `observe` / `screenshot`: Captura de pantalla codificada en Base64 PNG vía `PIL.ImageGrab` ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L303-L312)), resolución de monitor y listado de aplicaciones activas ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L273-L318)).
   - Nivel de riesgo asignado: `SecurityLevel.SAFE` / `RiskLevel.READ_ONLY` ([`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L79-L80); [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L71)).

2. **Control de Mouse:**
   - Acciones: `move`, `click` (izquierdo, derecho, central), `double_click`, `right_click`, `scroll` ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L385-L425)).
   - Validación: Comprobación estricta de límites de coordenadas contra la resolución activa de pantalla ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L350-L371)).
   - Nivel de riesgo asignado: `move` y `scroll` clasificados como `SecurityLevel.LOW`, clics clasificados como `SecurityLevel.HIGH` ([`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L81-L85)).

3. **Control de Teclado:**
   - Acciones: `write_text` (limitado a ráfagas de 1,000 caracteres, [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L470-L484)), `press_key` y `hotkey` ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L485-L521)).
   - Restricción: Lista blanca obligatoria `_ALLOWED_KEYS` con 60 teclas autorizadas ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L36-L45)). Cualquier tecla fuera de la lista es rechazada con `ExecutionStatus.FAILED` (Líneas 488–494, 511–518).
   - Nivel de riesgo asignado: `SecurityLevel.HIGH` ([`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L84-L85)).

4. **Gestión de Ventanas y Procesos:**
   - Acciones: `list_windows`, `focus_window`, `minimize_window`, `maximize_window`, `close_window` ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L550-L680)).
   - Implementación: Vía enumeración Win32 (`win32gui.EnumWindows`) y `psutil` ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L568-L587, L612-L634)).
   - Nivel de riesgo asignado: `focus_window` clasificado como `SecurityLevel.LOW`, cierre o manipulación como `SecurityLevel.HIGH` ([`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L81-L85)).

5. **Ciclo Percepción + Acción:**
   - Acción: `perceive_and_act` ([`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L693-L756)).
   - Flujo: Mide el estado inicial del escritorio, ejecuta la sub-acción y mide el estado posterior para detectar deltas (`delta_detected`).
   - Política: Aplica el principio Anti-Falso-Éxito: `verified=False` por defecto sin sensor externo de confirmación (Línea 743).

---

## 4. CÓMO PASA POR RISKENGINE / PERMISSIONMANAGER / AUTONOMYPOLICY

1. **Interacción con RiskEngine:**
   - **Evaluación en la Skill:** En [`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L64,L78-86), se instancia `RiskEngine()` y se asigna un nivel de seguridad estático inicial según la acción: `SAFE` para lectura/captura, `LOW` para foco/movimiento, y `HIGH` para pulsaciones físicas y clics.
   - **Motor de Reglas:** En [`core/risk_engine.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/risk_engine.py#L340-491), `RiskEngine.evaluate_risk()` evalúa la jerarquía formal (Líneas 25–31) a través de reglas modulares:
     - `SystemPathRiskRule` bloquea rutas de sistema como `system32` o `HKLM` (Líneas 180–226).
     - `PrivilegeRiskRule` detecta solicitudes de elevación UAC (Líneas 160–178).
     - Si la evaluación determina `DANGEROUS` o `CRITICAL`, marca automáticamente `requires_confirmation = True` (Líneas 470–474).

2. **Interacción con PermissionManager:**
   - En [`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L88-116), la skill consulta la autorización:
     - Si no se otorga el permiso, se genera un evento de auditoría `AuditEventType.EXECUTION_DENIED` (Líneas 98–109) y se devuelve `exito: False` con `security_verdict: "DENY"` (Líneas 110–116).
     - Si se otorga, se ejecuta y se audita el resultado con `AuditEventType.EXECUTION_SUCCEEDED` o `EXECUTION_FAILED` (Líneas 149–161).
   - En [`core/permission_manager.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/permission_manager.py#L89-175), el gestor aplica la política Fail-Safe (Default Deny). Niveles `CRITICAL` devuelven `PermissionDecision.DENY` (Línea 119), `DANGEROUS` devuelven `PermissionDecision.REQUIRE_CONFIRMATION` (Línea 129), y `SAFE` devuelven `PermissionDecision.ALLOW` (Línea 160).

3. **Interacción con AutonomyPolicy:**
   - En [`core/autonomy/autonomy_policy.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/autonomy/autonomy_policy.py#L187-363), la jerarquía inmutable establece `Policy -> DECISION`:
     - **Regla contra bypass:** Tareas programadas (`is_scheduled=True`, Líneas 285–295) y plugins (`is_plugin=True`, Líneas 299–309) tienen prohibido auto-ejecutar acciones peligrosas o críticas (`DENY`).
     - **Nivel de Autonomía 0 (OBSERVE):** Deniega cualquier acción de Computer Use que no sea de sólo lectura / `READ_ONLY` (Líneas 248–260).
     - **Nivel de Autonomía 1 (SUGGEST):** Suspende la acción y emite una propuesta para revisión (`REQUIRE_REVIEW`, Líneas 271–281).
     - **Detección de escalado no autorizado:** [`core/autonomy/autonomy_policy.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/autonomy/autonomy_policy.py#L365-L394) intercepta cadenas como `override_autonomy`, `bypass_confirmation` y lanza `AutonomyEscalationError` generando alerta de seguridad.

---

## 5. DÓNDE CORRE (HOST O SANDBOX)

- **Entorno de ejecución actual: HOST DIRECTO (Windows sin aislamiento).**
  - **Prueba en código:** En [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L58-L61,L334,L458), se importa `pyautogui` directamente en el proceso principal de Python y se deshabilita la protección de esquinas:
    ```python
    import pyautogui
    pyautogui.FAILSAFE = False
    ```
  - **Interacción directa con la sesión gráfica del usuario:** Las llamadas de mouse (`pyautogui.moveTo`, `click`, `scroll`) y teclado (`pyautogui.write`, `press`, `hotkey`) se inyectan directamente sobre la pantalla principal y activa del usuario.
  - **Manipulación Win32 directa:** [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L612-L634) y [`tools/desktop/ui_backend.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tools/desktop/ui_backend.py#L38) invocan directamente funciones del sistema operativo host (`win32gui.SetForegroundWindow`, `ShowWindow`, `comtypes`).
  - **Evaluación de aislamiento:** **CERO AISLAMIENTO**. No existe virtualización, ni contenedor Docker con display virtual (Xvfb/VNC), ni escritorio virtual aislado (Windows Virtual Desktop API / Session 0 isolation). Si la IA alucina un clic o una combinación de teclas, esta se ejecuta de inmediato sobre el escritorio personal del usuario.

---

## 6. QUÉ FALLA HOY EN CUA

1. **Riesgo Crítico de Inseguridad en el Host (Sin Sandbox y `FAILSAFE = False`):**
   - **Archivo:** [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L59)
   - Al establecer `pyautogui.FAILSAFE = False`, el usuario no puede abortar movimientos erráticos del cursor moviendo el mouse a la esquina de la pantalla.
   - Cualquier acción errónea impacta ventanas reales del sistema operativo anfitrión.

2. **Incompatibilidad con Entornos Headless / VPS sin Pantalla:**
   - **Archivo:** [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L154-L162,L309-L312)
   - En sistemas sin monitor físico o sesión de escritorio activa (como un servidor VPS Linux o Windows Server en modo servicio sin RDP interactivo), `pyautogui.size()` falla o devuelve `(0, 0)`, degradando el adapter a `DEGRADED` (Línea 156).
   - En ese estado, la captura de pantalla (`ImageGrab.grab()`, Línea 309) falla y retorna un PNG sintético de 1x1 píxeles (`"iVBORw0KGgo..."`, Línea 311). Esto inutiliza cualquier bucle de visión agéntica en un VPS.

3. **Bug Crítico de Firma de Métodos (Desconexión de API de Seguridad):**
   - **Archivo:** [`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L88-L95)
   - Invoca:
     ```python
     perm_granted = self.permission_manager.check_permission(
         skill_name="windows.computer_use",
         context={
             "action": accion,
             "risk_level": action_risk.value,
             "session_id": session_id,
         },
     )
     ```
   - **Archivo:** [`core/permission_manager.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/permission_manager.py#L177-L184)
   - La definición real del método es:
     ```python
     def check_permission(
         self,
         tool_name: str,
         operation: str = "execute",
         parameters: dict[str, Any] | None = None,
         risk_level: SecurityLevel | str = SecurityLevel.SAFE,
         user: str = "user",
     ) -> PermissionDecision:
     ```
   - **Consecuencia:** En ejecución real no mockeada, esta llamada genera un error fatal en tiempo de ejecución: `TypeError: PermissionManager.check_permission() got an unexpected keyword argument 'skill_name'`.
   - **Por qué no se detectó antes:** En la suite de pruebas ([`tests/skills/test_computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/skills/test_computer_use_skill.py#L36,L45,L61)), `check_permission` fue mockeado con `patch.object(..., return_value=True/False)`, ocultando la discrepancia de argumentos.

4. **Tratamiento Erróneo del Retorno de Permisos (`bool(Enum)`):**
   - **Archivo:** [`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L96)
   - Evalúa `if not perm_granted:`.
   - `PermissionManager.check_permission` retorna una instancia de `PermissionDecision` (`PermissionDecision.ALLOW`, `PermissionDecision.DENY`, `PermissionDecision.REQUIRE_CONFIRMATION`).
   - En Python, los miembros de un `StrEnum` evalúan como verdaderos (`bool("DENY") == True`), lo que causaría que incluso una denegación explícita fuese tratada como autorización concedida si la llamada no fallase por el `TypeError` anterior.

5. **Incapacidad de Grounding Visual en Modelos Locales Pequeños (Sin UI Automation):**
   - **Cita:** [`CUA_EVALUACION.md`](file:///d:/JESSYCA%203.0/asistente-jessyca/CUA_EVALUACION.md#L34-L36)
   - Modelos locales compactos (4B–8B) en Ollama tienen una tasa de error de puntería superior al 45% al intentar emitir coordenadas `[x, y]` crudas basadas únicamente en screenshots.
   - Jessyca compensa esto utilizando UIA semántico (`tools/desktop/ui_backend.py`), pero para aplicaciones que carecen de soporte de accesibilidad (ej. interfaces canvas o aceleradas por GPU), CUA no cuenta con un modelo de grounding local robusto sin consumir entre 4.5 GB y 6.0 GB de VRAM adicionales (OmniParser/YOLO).

6. **Inexistencia de Separación Arquitectónica de Modos (Modo Cliente vs Modo Dueño):**
   - Ni en [`skills/computer_use_skill.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py) ni en [`core/integration/adapters/computer_use_adapter.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py) existe discriminación de canal de origen (WhatsApp cliente vs identidad de dueño verificada).
   - Cualquier solicitud que alcance la skill puede disparar acciones de escritorio si no se añade una compuerta previa de autenticación biométrica/criptográfica.

---

## 7. RESUMEN DE LA EVALUACIÓN DE LA ETAPA 1

| Componente Evaluado | Estado Actual | Cita en Código | Veredicto |
| :--- | :--- | :--- | :---: |
| **Skill Registrada** | `windows.computer_use` (Nivel 3 / HIGH) | [`skills/computer_use_skill.py#L38-L62`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L38-L62) | **PASS** |
| **Adaptador Nativo** | `ComputerUseAdapter` (5 capacidades) | [`core/integration/adapters/computer_use_adapter.py#L64-L139`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L64-L139) | **PASS** |
| **Modelos Locales** | `qwen3-vl:4b` (visión) + `gemma4:e4b` / `llama3.1` | [`core/vision/vision_provider.py#L23`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/vision/vision_provider.py#L23) | **PASS** |
| **Gobernanza RiskEngine** | Reglas deterministas y confirmación en DANGEROUS/CRITICAL | [`core/risk_engine.py#L340-L491`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/risk_engine.py#L340-L491) | **PASS** |
| **Gobernanza AutonomyPolicy** | Cero auto-elevación; bloqueo en tareas programadas y plugins | [`core/autonomy/autonomy_policy.py#L283-L322`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/autonomy/autonomy_policy.py#L283-L322) | **PASS** |
| **Aislamiento de Ejecución** | **Sin Sandbox** (Host directo con `pyautogui.FAILSAFE=False`) | [`core/integration/adapters/computer_use_adapter.py#L58-L61`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L58-L61) | **FAIL (Inseguro)** |
| **Soporte Headless/VPS** | Degradado (`ImageGrab` dummy 1x1 sin display) | [`core/integration/adapters/computer_use_adapter.py#L153-L162`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/integration/adapters/computer_use_adapter.py#L153-L162) | **FAIL (Incompatible)** |
| **Integración Skill-Permission** | Firma rota (`TypeError: unexpected keyword 'skill_name'`) | [`skills/computer_use_skill.py#L88-L95`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L88-L95) vs [`core/permission_manager.py#L177-L184`](file:///d:/JESSYCA%203.0/asistente-jessyca/core/permission_manager.py#L177-L184) | **FAIL (Bug de código)** |
| **Doble Modo (Cliente/Dueño)** | No implementado en la skill ni en el adaptador | [`skills/computer_use_skill.py#L72-L130`](file:///d:/JESSYCA%203.0/asistente-jessyca/skills/computer_use_skill.py#L72-L130) | **FAIL (Falta compuerta)** |
