# REPORTE DE PERMISOS Y CONFINAMIENTO: ORCA + ADE (FASE 2)

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** Septiembre 2026  

---

## 1. Matriz de Permisos Granulares de Agentes

El módulo implementa un modelo de permisos de mínimos privilegios bajo la función `validate_agent_permissions()`.

| Permiso Granular | Estado en Fase 2 | Justificación y Ámbito |
| :--- | :---: | :--- |
| `READ_REPOSITORY` | **PERMITIDO** | Inspección de solo lectura del árbol de archivos del proyecto. |
| `WRITE_WORKTREE` | **PERMITIDO** | Escritura de modificaciones confinada a la rama temporal del worktree. |
| `CREATE_BRANCH` | **PERMITIDO** | Creación de ramas efímeras de Git para tareas asignadas. |
| `RUN_TESTS` | **PERMITIDO** | Ejecución de suites de prueba unitarias locales (`pytest`). |
| `READ_TEST_OUTPUT` | **PERMITIDO** | Lectura de reportes y salidas estándar de pruebas para diagnosticar errores. |
| `READ_CREDENTIALS` | **DENEGADO** | Prohibido el acceso a llaveros, tokens o credenciales del sistema. |
| `READ_ENV_SECRETS` | **DENEGADO** | Prohibida la lectura de variables de entorno confidenciales (`.env`). |
| `WRITE_PRODUCTION` | **DENEGADO** | Prohibida la escritura directa en ramas productivas o checkout principal. |
| `DELETE_SYSTEM_FILES` | **DENEGADO** | Prohibida la eliminación de archivos fuera del worktree temporal. |
| `MODIFY_JESSYCA_CONFIG` | **DENEGADO** | Prohibida la alteración de archivos de configuración de JESSYCA. |
| `CHANGE_SECURITY_POLICY` | **DENEGADO** | Prohibida la modificación de reglas del SecurityManager. |
| `CHANGE_JDE` | **DENEGADO** | Prohibida la alteración de políticas o decisiones del JDE. |
| `CHANGE_PERMISSION_MANAGER` | **DENEGADO** | Prohibida la auto-concesión de permisos adicionales. |

---

## 2. Confinamiento de Filesystem y Prevención de Traversal

* Las rutas de los worktrees se resuelven exclusivamente dentro de directorios temporales autorizados mediante `os.path.realpath` y `os.path.commonpath`.
* Cualquier intento de traversal (`..`, `%2e%2e`, bytes nulos o rutas de sistema tipo `C:\Windows`) es bloqueado con una excepción `ValueError`.
* Los worktrees eliminados no dejan rastros ni archivos huérfanos.

---

## 3. Veredicto de Permisos

```text
=====================================================
ORCA + ADE PHASE 2 PERMISSIONS VERDICT
=====================================================
ALLOWED PERMISSIONS: 5 (Strictly Sandboxed)
FORBIDDEN PERMISSIONS: 8 (Hard-Blocked)
PRIVILEGE ESCALATION: 0 VULNERABILITIES
STATUS: PASS
=====================================================
```
