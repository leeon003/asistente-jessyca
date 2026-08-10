# Captura de Pantalla y Visión de Escritorio — Jessyca Windows MCP (Subetapa 08.1)

## Visión General

La **Subetapa 08.1** inaugura la **Etapa 08 — Desktop Automation, Vision & OCR System** implementando la capability declarativa `windows.desktop` con su primera operación de inspección visual segura: `take_screenshot`.

---

## GARANTÍAS ABSOLUTAS DE SEGURIDAD Y PRIVACIDAD

1. **UNTRUSTED INPUT**: Todos los parámetros de captura (`x`, `y`, `width`, `height`, `format`, `quality`) son validados por `DesktopSecurityManager` aplicando el principio **FAIL-SAFE DENY**.
2. **CERO SUBPROCESS / SHELL**: La captura de pantalla se realiza directamente desde Python utilizando bibliotecas nativas de imagen en memoria o backends desacoplados. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**.
3. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`width`, `height`, `pixel_count`, `duration_ms`, `backend`). **NUNCA** almacenan bytes de imagen ni cadenas Base64.
4. **CERO BYPASS DE PIPELINE**: Toda solicitud atraviesa obligatoriamente la cadena completa de autorización: `CapabilityResolver` -> `RiskEngine` -> `SecurityPolicyEvaluator` -> `PermissionManager` -> `AuthorizationEvidence` -> `SecureExecutionBoundary`.

---

## Componentes Principales

### 1. `DesktopSecurityManager` (`core/desktop_security.py`)
- Valida coordenadas y dimensiones contra límites máximos configurados (`DESKTOP_MAX_WIDTH=3840`, `DESKTOP_MAX_HEIGHT=2160`, `DESKTOP_MAX_PIXELS=8294400`, `DESKTOP_MAX_CAPTURE_BYTES=10485760`).
- Impide coordenadas o dimensiones negativas (`x < 0`, `y < 0`, `width <= 0`, `height <= 0`), desbordamientos numéricos en multiplicación de píxeles y formatos no autorizados.

### 2. Backends Desacoplados (`tools/desktop/backend.py`)
- `IDesktopCaptureBackend`: Protocolo abstracto para captura de escritorio.
- `WindowsDesktopCaptureBackend`: Captura nativa en memoria utilizando Pillow (`PIL.ImageGrab`).
- `FakeDesktopCaptureBackend`: Backend sintético seguro en memoria para pruebas unitarias y entornos multiplataforma o headless sin sesión gráfica.

### 3. Modelos Inmutables (`core/desktop_models.py`)
- `@dataclass(frozen=True)` `ScreenshotRequest`: `x`, `y`, `width`, `height`, `format`, `quality`.
- `@dataclass(frozen=True)` `ScreenshotMetadata`: `width`, `height`, `format`, `size_bytes`, `pixel_count`, `timestamp`, `backend`.
- `@dataclass(frozen=True)` `ScreenshotResult`: `metadata`, `image_base64`.

### 4. Servicio y Ejecutor (`tools/desktop/desktop_service.py` & `executor.py`)
- `DesktopService`: Orquesta la validación de seguridad, ejecución del backend y registro de metadatos de auditoría sin filtración binaria.
- `WindowsDesktopToolExecutor`: Integrado en `SecureExecutionPipeline` para el dominio `windows.desktop`.
