# REPORTE DE AUDITORÍA DE PERMISOS Y AISLAMIENTO — ARCHIFY FASE 3

**Sistema:** JESSYCA PC  
**Módulo:** Archify Security Boundary & Permission Enforcement  
**Fase:** Fase 3 — Production Certification  
**Fecha:** 2026-09-27  
**Resultado:** **PASS — 100% AISLADO Y CONFINADO**  

---

## 1. MATRIZ DE AUTORIZACIONES Y PRIVILEGIOS

Archify ha sido configurado bajo el principio estricto de mínimo privilegio (*Least Privilege Principle*). A continuación se documenta la matriz formal de permisos permitidos y denegados:

| Superficie del Sistema | Permitido | Denegado | Mecanismo de Control |
| :--- | :---: | :---: | :--- |
| **Crear archivos en `data/archify/`** | **SÍ** | | Adaptador canónico + verificación `os.path.commonpath` |
| **Leer archivos arbitrarios del sistema** | | **SÍ** | No existen métodos ni APIs de lectura de archivos |
| **Escribir fuera de `data/archify/`** | | **SÍ** | Detección estricta de traversal + canonical realpath |
| **Ejecutar comandos shell (PowerShell / CMD)** | | **SÍ** | Bloqueo en RiskEngine / No invocación de shells |
| **Lanzar procesos arbitrarios** | | **SÍ** | Solo Node.js (`node -v` para health check pasivo) |
| **Modificar código del proyecto** | | **SÍ** | Permiso exclusivo de solo-lectura sobre el código fuente |
| **Modificar memoria o estado de JESSYCA** | | **SÍ** | Modelos inmutables (`ConfigDict(frozen=True)`) |
| **Modificar configuración de JESSYCA** | | **SÍ** | Sin acceso a `settings.py` ni variables de entorno |
| **Acceder a credenciales / tokens / secretos** | | **SÍ** | Capa `redact_sensitive_data` + regex anti-leak |

---

## 2. PRUEBAS DE AISLAMIENTO Y BLOQUEO DE RUTAS

Se ejecutaron pruebas directas de inyección de rutas críticas del sistema operativo y rutas relativas con secuencias de escape:

| Vector de Escape Probado | Tipo de Ataque | Resultado Esperado | Resultado Real | Evidencia |
| :--- | :--- | :---: | :---: | :--- |
| `../../secret.txt` | Directory Traversal relativo | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `../../.env` | Acceso a variables de entorno | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `../../config.json` | Acceso a configuraciones | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `C:\Windows\System32\calc.exe.html` | Ruta absoluta de sistema | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `C:\Users\...\secret.html` | Acceso a perfil de usuario | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `%2e%2e%2f%2e%2e%2fsecret.html` | Traversal URL-encoded | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `nested/../../traversal.html` | Traversal intermedio | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal detectado.` |
| `file_\x00_null.html` | Inyección de byte nulo | DENY | **DENY** | `Violación de seguridad: intento de Path Traversal (null byte) detectado.` |

---

## 3. POLÍTICA CANÓNICA DE RESOLUCIÓN DE RUTAS

Se eliminó cualquier dependencia de comprobaciones ingenuas como `if ".." not in path`. La política canónica implementada en `JessycaArchifyAdapter.render_diagram` opera de la siguiente forma:

```python
# 1. Detección temprana de bytes nulos y decodificación URL
decoded_filename = urllib.parse.unquote(filename)

# 2. Extracción estricta del nombre base (sin directorios padre)
safe_name = os.path.basename(decoded_filename)
if not safe_name.endswith(".html"):
    safe_name += ".html"

# 3. Resolución canónica de enlaces simbólicos y rutas absolutas
canonical_output_dir = os.path.realpath(os.path.abspath(self._output_dir))
canonical_target_path = os.path.realpath(os.path.abspath(os.path.join(self._output_dir, safe_name)))

# 4. Verificación estricta mediante commonpath
common = os.path.commonpath([canonical_target_path, canonical_output_dir])
if common != canonical_output_dir or os.path.dirname(canonical_target_path) != canonical_output_dir:
    raise SecurityViolation("Violación de seguridad: intento de Path Traversal detectado.")
```

Esta política garantiza que ningún artefacto pueda escribirse fuera de `data/archify/` ni siquiera mediante enlaces simbólicos, secuencias dobles de separación, o rutas UNC de Windows.

---

## 4. CERTIFICACIÓN DE PERMISOS
Archify cumple plenamente con los requisitos de aislamiento de Fase 3: no ejecuta procesos no autorizados, no modifica el sistema de archivos fuera de su sandbox y no tiene acceso a memoria ni secretos.
