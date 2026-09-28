# AUDITORÍA DE SEGURIDAD: INTEGRACIÓN ARCHIFY

**Fecha:** 2026-09-27  
**Autor:** Arquitecto Principal JESSYCA PC  
**Objetivo:** Auditar posibles vectores de ataque, riesgos de inyección de código y acceso a recursos al procesar diagramas con Archify.

---

## 1. VECTORES DE RIESGO ANALIZADOS

### A. Ejecución de Código Arbitrario (RCE)
* **Vector:** Archify procesa JSON de entrada y genera HTML. Si los nodos o etiquetas contienen `<script>` o eventos JavaScript no sanitizados (`onload=`, `onerror=`), podría producirse Cross-Site Scripting (XSS) al abrir el HTML en el navegador.
* **Mitigación JESSYCA:** El `JessycaArchifyAdapter` implementa un sanitizador estricto de texto que escapa caracteres HTML (`<`, `>`, `&`, `"`, `'`) en todos los nombres de nodos, etiquetas de aristas y descripciones antes de pasarlos al renderer.

### B. Path Traversal en Archivos de Salida
* **Vector:** Si un parámetro especifica una ruta como `../../Windows/System32/evil.html`.
* **Mitigación JESSYCA:** La ruta de salida está estrictamente confinada a un directorio de trabajo seguro dentro de `data/archify/` o dentro de la carpeta del proyecto actual del usuario, verificando mediante `os.path.abspath` y `os.path.commonpath`.

### C. Consumo Indebido de Recursos (DoS / Zip Bombs / Mega JSON)
* **Vector:** Generación de especificaciones de diagramas con millones de nodos o aristas circulares que bloqueen la CPU.
* **Mitigación JESSYCA:** Límites duros impuestos en el adaptador:
  * Máximo 100 nodos por diagrama (recomendado <= 12 para legibilidad).
  * Máximo 200 conexiones/aristas.
  * Timeout de compilación de 5.0 segundos.

### D. Fuga de Secretos en Nombres de Nodos
* **Vector:** Diagramas que incluyan tokens de API, cadenas de conexión con contraseñas o claves privadas.
* **Mitigación JESSYCA:** El adaptador aplica la función `redact_sensitive_data()` de JDE antes de renderizar la especificación JSON.

---

## 2. MATRIZ DE PERMISOS (PRINCIPIO DE MÍNIMO PRIVILEGIO)

| Operación | Nivel de Riesgo | Confirmación Humana Requerida | Permiso Requerido |
|---|---|---|---|
| `archify.validate` | `SAFE` | No | `tools:archify` |
| `archify.render` (Sandbox local) | `SAFE` | No | `tools:archify` |
| `archify.export` (Escritura en disco) | `LOW` | No | `tools:archify`, `filesystem:write` |
| `archify.open_in_browser` | `SAFE` | No | `browser:open` |

---

## 3. DICTAMEN DE SEGURIDAD

**ESTADO: APROBADO CON CONTROLES (PASS)**.  
Con las medidas de sanitización, confinamiento de rutas de salida, redacción de secretos y límites de complejidad, la integración de Archify a través del Adapter no presenta riesgos para la seguridad del host ni para la confidencialidad del usuario.
