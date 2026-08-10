# Motor de Extracción de Texto OCR — Jessyca Windows MCP (Subetapa 08.2)

## Visión General

La **Subetapa 08.2** amplía la **Etapa 08 — Desktop Automation, Vision & OCR System** implementando el motor seguro de extracción de texto OCR (`ocr_screen`) bajo la capability `windows.desktop`.

---

## GARANTÍAS ABSOLUTA DE SEGURIDAD Y PRIVACIDAD

1. **UNTRUSTED INPUT**: Todos los parámetros de solicitud OCR (coordenadas, dimensiones, formatos, idiomas, regiones, confianzas) son validados por `OCRSecurityManager` aplicando el principio **FAIL-SAFE DENY**.
2. **SANITIZACIÓN DE TEXTO Y REDACCIÓN DE SECRETOS**: Todo el texto reconocido y las regiones individuales son procesadas por `OCRTextSanitizer` (que integra `SecretRedactor`) para redactar automáticamente contraseñas (`password=...`), API keys, tokens Bearer/JWT, llaves privadas y URLs de conexión antes de devolver los resultados.
3. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`char_count`, `region_count`, `avg_confidence`, `processing_time_ms`, `backend_name`). **NUNCA** almacenan imágenes Base64 ni el texto completo del OCR con datos sensibles.
4. **CERO SUBPROCESS / SHELL**: La extracción se ejecuta mediante bibliotecas de visión en memoria o un `FakeOCRBackend` sintético desacoplado para entornos de prueba. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**.

---

## Componentes Principales

### 1. `OCRSecurityManager` (`core/ocr_security.py`)
- Valida coordenadas y dimensiones contra límites máximos configurados (`OCR_MAX_SCREEN_WIDTH=3840`, `OCR_MAX_SCREEN_HEIGHT=2160`, `OCR_MAX_REGIONS=500`, `OCR_MAX_TEXT_LENGTH=50000`, `OCR_MAX_INPUT_BYTES=10485760`).
- Rechaza valores de confianza fuera de rango, NaN, Infinity, coordenadas o dimensiones negativas y desbordamientos numéricos en bounding boxes.

### 2. `OCRTextSanitizer` (`core/ocr_sanitizer.py`)
- Normaliza codificación UTF-8, elimina caracteres de control y aplica `SecretRedactor` para proteger credenciales y secretos detectados visualmente en pantalla.

### 3. Backends OCR Desacoplados (`tools/desktop/ocr_backend.py`)
- `IOCRBackend`: Protocolo abstracto para backends de reconocimiento OCR.
- `WindowsOCRBackend`: Backend desacoplado que utiliza Pytesseract / Windows Media OCR con fallback limpio.
- `FakeOCRBackend`: Backend sintético seguro en memoria para pruebas unitarias deterministas y entornos headless.

### 4. Servicio y Ejecutor (`tools/desktop/ocr_service.py` & `executor.py`)
- `OCRService`: Orquesta la validación de seguridad, ejecución del backend, sanitización de texto y registro de auditoría.
- `WindowsDesktopToolExecutor`: Actualizado para soportar `ocr_screen` dentro de `SecureExecutionPipeline`.
