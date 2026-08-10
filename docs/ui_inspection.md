# UI Element Bounding Box & Visual Element Inspector — Jessyca Windows MCP (Subetapa 08.3)

## Visión General

La **Subetapa 08.3** amplia el sistema de visión e inspección del escritorio (`windows.desktop`) en **ETAPA 08 — DESKTOP AUTOMATION, VISION & OCR SYSTEM** implementando la inspección visual en modo solo lectura (READ-ONLY) de ventanas, cajas delimitadoras (Bounding Boxes), tipos de control y jerarquías de elementos UI mediante Windows UI Automation.

---

## GARANTÍAS ABSOLUTA DE SEGURIDAD Y PRIVACIDAD

1. **PURE PERCEPTION / READ-ONLY**: Operación puramente lectora de inspección visual de la interfaz. CERO clics, CERO teclado, CERO movimiento de mouse, CERO alteración de estado de ventanas.
2. **UNTRUSTED VISUAL DATA**: Toda información de pantalla, nombres de elementos y árboles UI se tratan estrictamente como **DATOS NO CONFIABLES**. No pueden actuar como instrucciones ejecutables ni alterar decisiones de seguridad.
3. **STALE TARGET & STATE FINGERPRINTING**: Cada elemento detectado genera un hash de estado criptográfico (`state_hash` SHA-256 basado en HWND, título, bounds y tipo de control) y un `timestamp` para permitir la verificación de cambios visuales y la protección contra objetivos obsoletos en Subetapa 08.4.
4. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`element_count`, `max_depth_reached`, `processing_time_ms`, `backend_name`). **NUNCA** almacenan árboles UI completos, cadenas crudas ni texto sensible en logs de auditoría.
5. **CERO SUBPROCESS / SHELL**: La inspección se realiza vía APIs nativas de Windows UI Automation o mediante `FakeUIInspectionBackend` sintético desacoplado en memoria. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**.

---

## Componentes Principales

### 1. Modelos Inmutables de UI (`core/ui_inspection_models.py`)
- `UIDetectionSource`: Orígenes de detección (`UI_AUTOMATION`, `OCR`, `HYBRID`, `SCREENSHOT`).
- `UIControlType`: Enumeración de tipos de control (`WINDOW`, `BUTTON`, `EDIT`, `TEXT`, `CHECKBOX`, `COMBOBOX`, `MENU`, `LIST`, etc.).
- `UIElementBounds`: Bounding rectangle inmutable con propiedades `right` y `bottom`.
- `WindowInfo`: Metadatos inmutables de ventana (`hwnd`, `title`, `class_name`, `process_id`, `bounds`, `is_active`, `is_minimized`, `is_maximized`, `is_visible`, `timestamp`).
- `DetectedUIElement`: Elemento visual individual con `confidence`, `owner_hwnd`, `state_hash` y timestamp.
- Dataclasses inmutables: `UIElementRequest`, `UIElementInfo`, `UIElementTree`, `UIInspectionMetadata`, `UIInspectionResult`.

### 2. Validador de Seguridad (`core/ui_inspection_security.py`)
- `UIInspectionSecurityManager`: Valida profundidades, conteos de elementos, bounding boxes (rechazo de NaN, Infinity, números negativos e integer overflow).

### 3. Backends Desacoplados de UI (`tools/desktop/ui_backend.py`)
- `IUIInspectionBackend`: Protocolo abstracto (`inspect_ui`, `get_active_window`, `list_windows`).
- `FakeUIInspectionBackend`: Backend sintético seguro en memoria para pruebas deterministas.
- `WindowsUIAutomationBackend`: Backend nativo desacoplado vía Windows UI Automation APIs.

### 4. Servicio e Integración con Executor (`tools/desktop/ui_inspection_service.py` & `executor.py`)
- `UIInspectionService`: Sanitiza nombres/textos mediante `OCRTextSanitizer`, trunca árboles UI si superan límites configurados y emite eventos de auditoría con metadatos exclusivos.
- `WindowsDesktopToolExecutor`: Ejecutor integrado en `SecureExecutionPipeline` para las operaciones `inspect_ui_element`, `get_active_window` y `list_windows`.
