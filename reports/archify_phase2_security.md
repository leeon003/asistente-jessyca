# AUDITORÍA Y SEGURIDAD — ARCHIFY FASE 2 (CONTROLLED ACTIVE)

**Sistema:** JESSYCA PC  
**Módulo:** Seguridad y Confinamiento de Archify  
**Fecha:** 2026-09-27  
**Estado:** **PASSED — HARDENED & CONFINED**  

---

## 1. MODELO DE AMENAZAS Y SUPERFICIE DE ATAQUE

Al pasar Archify a modo `CONTROLLED ACTIVE`, el sistema genera artefactos HTML/SVG reales en el disco local y los presenta al usuario o interfaz web. Esto introduce vectores potenciales de ataque que han sido formalmente analizados y neutralizados:

| Vector de Amenaza | Riesgo Potencial | Mecanismo de Mitigación Implementado | Estado |
| :--- | :--- | :--- | :---: |
| **Cross-Site Scripting (XSS)** | Inyección de `<script>`, `<img onerror>` o `javascript:` en títulos, nodos o aristas. | Sanitización recursiva con `html.escape()` en todos los campos de texto del IR. | **BLOQUEADO** |
| **Path Traversal / Escape de Confinamiento** | Sobrescritura de archivos del sistema operativo mediante `../../` o rutas absolutas. | Confinamiento estricto en `data/archify/`, saneamiento de nombres con `os.path.basename` y validación de prefijo absoluto. | **BLOQUEADO** |
| **Fuga de Secretos en Diagramas** | Exposición involuntaria de tokens, passwords o API keys en artefactos visuales. | Capa de redacción automática `redact_sensitive_data` antes de compilar y verificación regex post-compilación en `ExecutionVerifier`. | **BLOQUEADO** |
| **Denegación de Servicio (DoS)** | Especificaciones masivas (ej. 10,000 nodos) que congelen la CPU o consuman disco. | Límites duros incondicionales: `max_nodes = 100`, `max_edges = 200`, `max_file_size = 5MB`. | **BLOQUEADO** |
| **Falso Éxito (False Success)** | Notificar al usuario que el diagrama fue creado cuando el archivo está corrupto o vacío. | Verificación determinista obligatoria por `ExecutionVerifier` antes de emitir éxito. | **BLOQUEADO** |

---

## 2. DETALLE DE CONTROLES DE SEGURIDAD

### A. Sanitización XSS Estricta
Todo campo de entrada proveniente del usuario o del modelo de lenguaje es procesado por `sanitize_spec()`:
```python
def _clean_value(val: Any) -> Any:
    if isinstance(val, str):
        return html.escape(val)
    elif isinstance(val, dict):
        return {k: _clean_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_clean_value(item) for item in val]
    return val
```
Pruebas ejecutadas con payloads como:
* `<script>alert('xss_title')</script>` -> Convertido a `&lt;script&gt;alert('xss_title')&lt;/script&gt;`
* `<img src=x onerror=alert('xss_node')>` -> Convertido a `&lt;img src=x onerror=alert('xss_node')&gt;`
* `<iframe src=javascript:alert(1)></iframe>` -> Convertido a `&lt;iframe src=javascript:alert(1)&gt;&lt;/iframe&gt;`

En el archivo HTML final generado, ninguna etiqueta ejecutable permanece viva.

### B. Confinamiento de Rutas (Sandbox de Salida)
El adaptador resuelve y confina todas las rutas de salida exclusivamente dentro de:
```text
D:\JESSYCA 3.0\asistente-jessyca\data\archify\
```
Controles aplicados:
1. Rechazo inmediato si el nombre contiene secuencias `..`, `/`, `\`, `:` o rutas absolutas.
2. Extracción del nombre base seguro: `safe_name = os.path.basename(base_name)`.
3. Verificación de prefijo canónico:
   ```python
   if not target_path.startswith(os.path.abspath(self._output_dir)):
       return False, "Violación de seguridad: intento de Path Traversal detectado.", ""
   ```

### C. Redacción y Filtrado de Datos Sensibles
Antes del procesamiento del diagrama, el objeto JSON es filtrado mediante `redact_sensitive_data()`. Cualquier clave sensible (`api_key`, `password`, `token`, `secret`, `credentials`) es sustituida por `***REDACTED_SECRET***`.
Adicionalmente, el `ExecutionVerifier` realiza un escaneo secundario sobre el archivo HTML compilado para confirmar que ninguna credencial haya eludido la primera barrera.

### D. Límites de Complejidad (Anti-DoS)
La validación previa al renderizado (`validate_spec`) aplica:
* `nodes <= 100`: Peticiones con 101 nodos son rechazadas inmediatamente sin invocar el compilador.
* `edges <= 200`: Peticiones con 201 aristas son rechazadas inmediatamente.
* `file_size <= 5MB`: Si por alguna anomalía el archivo excede 5MB, el `ExecutionVerifier` lo declara `VERIFICATION_FAILED`.

---

## 3. RESULTADOS DE LAS PRUEBAS DE SEGURIDAD

| Caso de Prueba | Payload Inyectado | Comportamiento Esperado | Resultado Real | Estado |
| :--- | :--- | :--- | :--- | :---: |
| `test_06_failure_injection_path_traversal_blocked` | `../../malicious.html` | Rechazado con error de seguridad | Rechazado sin escritura | **PASS** |
| `test_07_failure_injection_xss_sanitization` | `<script>alert(1)</script>` | Escapado como entidades HTML | Escapado (`&lt;script&gt;`) | **PASS** |
| `test_08_failure_injection_dos_limits_enforced` | 120 nodos | Rechazado por límite excedido | Rechazado formalmente | **PASS** |
| `test_09_failure_injection_secrets_redacted` | `api_key: SUPER_SECRET` | Reemplazado por redaction token | Redactado a `***REDACTED_SECRET***` | **PASS** |
| `test_10_security_path_traversal_blocked` | `C:\Windows\System32\evil.html` | Bloqueo absoluto de path traversal | Bloqueado | **PASS** |
| `test_11_security_secrets_redacted_in_artifact` | `token: Bearer eyJ...` | Ausente en el archivo HTML | Redactado en disco | **PASS** |
| `test_14_execution_verifier_detects_tampered` | Archivo vacío (0 bytes) | Calificado como `VERIFICATION_FAILED` | `is_verified=False` | **PASS** |

---

## 4. CONCLUSIÓN DE SEGURIDAD

Archify en Fase 2 opera bajo un modelo de contención y aislamiento estricto. No existe riesgo de ejecución remota de código (RCE), escape de directorio ni persistencia no autorizada.
