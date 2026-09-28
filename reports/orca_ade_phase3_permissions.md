# JESSYCA PC — ORCA + ADE FASE 3 PERMISSIONS & GOVERNANCE REPORT

## GOBERNANZA Y GESTIÓN DE PERMISOS

### 1. Marco de Permisos Granulares
El modelo formal `OrcaPermission` define los permisos accesibles para agentes de orquestación:
* `OrcaPermission.READ_REPOSITORY` (Lectura segura de archivos dentro del repositorio de trabajo)
* `OrcaPermission.WRITE_WORKTREE` (Escritura y mutación dentro del worktree efímero asignado)
* `OrcaPermission.RUN_TESTS` (Ejecución de tests mediante pytest en sandbox)
* `OrcaPermission.PROPOSE_CHANGES` (Propuesta de parches hacia el Review Gate)

### 2. Permisos Prohibidos / Denegación Inmediata
Cualquier solicitud que incluya los siguientes permisos es abortada inmediatamente con estado `DENIED` sin efectos laterales:
* `OrcaPermission.READ_CREDENTIALS` (Acceso a secretos, variables de entorno o almacén de llaves)
* `OrcaPermission.MODIFY_SYSTEM` (Modificación de configuración del host o sistema operativo)
* `OrcaPermission.UNRESTRICTED_NETWORK` (Acceso irrestricto a red externa)
* `OrcaPermission.EXECUTE_ARBITRARY` (Ejecución de binarios arbitrarios fuera de allowlist)
* `OrcaPermission.CHANGE_JDE` (Intento de reconfigurar o puentear el motor de decisiones JDE)

### 3. Matriz de Evaluación
La función `validate_agent_permissions()` valida cada solicitud contra la política de seguridad corporativa. Si un solo permiso no está autorizado, la solicitud completa es rechazada sin ejecución parcial.
