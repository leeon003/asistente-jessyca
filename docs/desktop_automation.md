# Secure Desktop Automation Boundary — Jessyca Windows MCP (Subetapa 08.4)

## Visión General

La **Subetapa 08.4** concluye y cierra oficialmente la **Etapa 08 — Desktop Automation, Vision & OCR System** implementando la frontera de ejecución segura de acciones sobre la interfaz gráfica de Windows (`click_element`, `type_text`, `focus_window`, `drag_and_drop`) bajo la capability `windows.desktop`.

---

## GARANTÍAS ABSOLUTAS DE SEGURIDAD Y PRIVACIDAD

1. **EMERGENCY STOP OVERRIDE**: Mecanismo global y thread-safe `EmergencyStopManager`. Si está **ACTIVO**, toda acción de automatización UI es **DENEGADA INMEDIATAMENTE** con máxima prioridad (sobreescribe cualquier `ALLOW` o confirmación).
2. **UNTRUSTED ACTION INPUT & STALE TARGET PROTECTION**: Todos los targets y parámetros son validados por `DesktopAutomationSecurityManager` (**FAIL-SAFE DENY**). Si la identidad del target (PID, HWND, Bounding Box) ya no coincide con la interfaz real -> `STALE_TARGET -> DENY`.
3. **VINCULACIÓN CRIPTOGRÁFICA CON HUELLA SHA-256**: Cada acción genera y verifica una firma SHA-256 (`action_fingerprint`) que vincula el nombre de la herramienta, tipo de acción, target, coordenadas y argumentos con la `AuthorizationEvidence`. Alteración post-autorización -> `DENY`.
4. **INVARIANTE DE PRIVACIDAD EN TYPE_TEXT**: El texto escrito mediante `type_text` **NUNCA SE REGISTRA** en `AuditLogger`, `EventBus`, logs, excepciones o metadatos. Se registra únicamente metadatos (`text_length`, `text_hash`, `target_summary`, `action_type`, `request_id`).
5. **CERO SUBPROCESS / SHELL**: La automatización gráfica utiliza la API nativa de Windows UI Automation / SendInput o un `FakeDesktopAutomationBackend` sintético desacoplado en memoria. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**.

---

## Componentes Principales

### 1. `EmergencyStopManager` (`core/emergency_stop.py`)
- Gestor singleton thread-safe con operaciones `activate()`, `deactivate()`, `is_active()`.

### 2. `DesktopAutomationSecurityManager` (`core/desktop_automation_security.py`)
- Valida coordenadas contra límites máximos configurados (`DESKTOP_MAX_WIDTH=3840`, `DESKTOP_MAX_HEIGHT=2160`, `DESKTOP_AUTOMATION_MAX_TEXT_LENGTH=4096`, `DESKTOP_AUTOMATION_MAX_DRAG_DISTANCE=3840`).
- Verifica huellas criptográficas SHA-256 y frescura de targets UI.

### 3. Backends de Automatización Desacoplados (`tools/desktop/automation_backend.py`)
- `IDesktopAutomationBackend`: Protocolo abstracto para ejecución gráfica.
- `WindowsDesktopAutomationBackend`: Backend nativo utilizando Windows UI Automation / SendInput con fallback limpio.
- `FakeDesktopAutomationBackend`: Backend sintético seguro en memoria para pruebas unitarias deterministas.

### 4. Servicio y Ejecutor (`tools/desktop/automation_service.py` & `executor.py`)
- `DesktopAutomationService`: Orquesta la validación de seguridad, verificación de Parada de Emergencia, huella SHA-256, ejecución del backend y registro de auditoría con privacidad.
- `WindowsDesktopToolExecutor`: Integración completa de `click_element`, `type_text`, `focus_window`, `drag_and_drop` dentro de `SecureExecutionPipeline`.
