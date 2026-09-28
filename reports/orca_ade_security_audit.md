# AUDITORÍA DE SEGURIDAD Y THREAT MODEL: ORCA + ADE

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Fecha:** Septiembre 2026  

---

## 1. Executive Summary

La arquitectura nativa de **Orca** está concebida como un orquestador para desarrolladores humanos (*developer-centric cockpit*), donde se asume que el usuario tiene privilegios para ejecutar herramientas CLI en su máquina local. En consecuencia, **Orca no cuenta de forma nativa con un sandbox restrictivo de ejecución de comandos**, sino que delega la seguridad en la confianza del usuario y en los límites del propio sistema operativo.

Para **JESSYCA PC**, este modelo representaría un riesgo **CRÍTICO** si se conectara de forma directa o sin mediación. 

Por ello, la integración en JESSYCA se sujeta a la regla inviolable de **cero privilegios directos**: Orca solo interactuará a través de un **Adapter aislado (LAB/SHADOW)** donde cualquier acción o propuesta de comando deba pasar obligatoriamente por el **RiskEngine**, el **PermissionManager** y la autorización expresa del **JDE**.

---

## 2. Threat Modeling y Superficies de Ataque

Se analizaron 20 superficies de ataque potenciales asociadas a las capacidades y mecanismos de Orca:

| Vector de Amenaza | Mecanismo en Orca Nativo | Severidad | Mitigación Mandatoria en JESSYCA |
| :--- | :--- | :---: | :--- |
| **Command Execution** | Invoca shells (`cmd.exe`, `powershell.exe`, `bash`) mediante `node-pty`. | **CRITICAL** | **PROHIBIDO:** Orca Adapter jamás invocará shells del sistema de forma autónoma. Solo emite propuestas a JDE. |
| **Shell Execution / Spawn** | Crea procesos secundarios sin restricción de comandos. | **CRITICAL** | Subordinado a la Security Layer de JESSYCA. Bloqueo en tiempo de diseño. |
| **Arbitrary Code Execution** | Los agentes orquestados pueden escribir y ejecutar scripts en disco. | **CRITICAL** | Todo script o tool debe ser auditado por `RiskEngine` y verificado por `ExecutionVerifier`. |
| **Privilege Escalation** | Ejecuta con los permisos del usuario que inicia el entorno. | **HIGH** | El adapter de JESSYCA se ejecuta en un contexto de mínimos privilegios sin elevación UAC. |
| **Filesystem Access** | Modifica cualquier directorio accesible por el repositorio Git. | **HIGH** | **Confinamiento estricto:** Solo acceso a worktrees temporales acotados en `data/orca_worktrees/` o repo de pruebas. |
| **Path Traversal** | Parámetros de ruta en comandos git o CLI (`../../`). | **HIGH** | Validación canónica de rutas con `os.path.realpath` y `commonpath`. |
| **Credential Access** | Lee variables de entorno del host (`.env`, tokens de APIs, git credentials). | **HIGH** | Redacción total de secretos antes de transferir contexto al adapter de Orca. |
| **Secret Leakage** | Transcripciones PTY y logs guardan salidas de terminal. | **HIGH** | Módulo de redacción regex en pipeline de observabilidad. |
| **Prompt Injection** | Entradas del usuario o contenido web procesado por agentes. | **HIGH** | Sanitización y filtrado de prompts por parte del Core antes de formular la tarea. |
| **Tool Injection** | Invocación de tools no autorizadas mediante `SKILL.md`. | **HIGH** | Registro cerrado de capacidades certificadas. Bloqueo de skills dinámicas no auditadas. |
| **Network Access / SSRF** | Chromium embebido ("Design Mode") navega a URLs arbitrarias. | **MEDIUM** | Desactivación de navegación libre en modo LAB; solo loopback o páginas locales fijas. |
| **Data Exfiltration** | Envío de telemetría o código a servicios remotos/móviles. | **MEDIUM** | Modo local estricto (*Local-First*), sin puentes de red externos no autenticados. |
| **Remote Execution (SSH)** | Soporte para worktrees remotos vía SSH. | **HIGH** | **DESHABILITADO en JESSYCA:** Toda experimentación se mantiene estrictamente local. |
| **Persistence** | Configuración de daemons de fondo (`orcad`). | **MEDIUM** | En modo LAB/SHADOW no se permite la instalación de servicios persistentes de SO. |
| **Unsafe Deserialization** | Intercambio de mensajes JSON-RPC e IPC. | **LOW** | Validación tipada de esquemas (`Pydantic` / `dataclasses`) sin `eval` ni `pickle`. |
| **Arbitrary Python Exec** | Scripts de build o helpers externos. | **HIGH** | Todo código Python se ejecuta en el entorno controlado de tests de JESSYCA sin `exec()` dinámico. |
| **Sandbox Escape** | Intento de saltar del worktree al sistema raíz. | **HIGH** | Validación del directorio de trabajo canónico en cada operación. |
| **Process Spawning** | Creación masiva de procesos que cause DoS/Fork-bomb. | **MEDIUM** | Límite máximo estricto de workers concurrentes (máximo 4 en LAB). |
| **Plugin Loading** | Carga dinámica de bundles de skills. | **MEDIUM** | Solo bundles criptográficamente validados con hash inmutable. |
| **Dynamic Imports** | Importación no controlada de módulos en runtime. | **LOW** | Lista blanca de dependencias estáticas en el adapter. |

---

## 3. Auditoría de Mecanismos de Ejecución en Orca

Al auditar el código fuente del proyecto [github.com/stablyai/orca](https://github.com/stablyai/orca):

1. **node-pty & Shell Spawner:**
   * Orca emplea la librería `node-pty` para abrir terminales virtuales conectadas al shell por defecto del usuario (`powershell.exe` o `cmd.exe` en Windows, `/bin/zsh` en macOS).
   * **Hallazgo:** Cualquier comando enviado a la sesión del agente se interpreta directamente por el intérprete de comandos del host.
   * **Veredicto JESSYCA:** Este mecanismo no puede ser utilizado de forma descontrolada por JESSYCA. En la integración LAB, el adapter no invocará `node-pty` ni shells reales del host.

2. **Comandos Git (`git worktree`):**
   * Orca invoca binarios de Git para gestionar ramas y worktrees.
   * **Hallazgo:** Si no se sanitizan los nombres de rama o rutas, es posible inyectar parámetros de comando de Git (`--upload-pack`, etc.).
   * **Mitigación JESSYCA:** En el sandbox del LAB, los nombres de rama y directorios se validan mediante expresiones regulares estrictas `^[a-zA-Z0-9_\-\./]+$`.

3. **RPC y IPC Interno:**
   * La comunicación entre el proceso Main de Electron y los renderers o daemons se realiza mediante serialización JSON.
   * **Hallazgo:** No se observó uso de `eval()` ni de des-serialización insegura tipo `pickle`.
   * **Veredicto JESSYCA:** La interfaz de datos es segura a nivel de deserialización.

---

## 4. Política de Aislamiento Mandatoria para el LAB de JESSYCA

Para cumplir con la directiva de la Fase 1, el módulo experimental `core/orca_ade/` y el sandbox `lab/orca_ade/` implementan las siguientes restricciones inquebrantables:

```text
1. MODO RESTRINGIDO:
   - Modos permitidos: OFF, LAB, SHADOW.
   - Modo ACTIVE: PROHIBIDO en Fase 1.

2. SUBORDINACIÓN AL JDE:
   - Orca Adapter genera exclusivamente PROPUESTAS (OrcaAdeProposal).
   - El JDE decide si la propuesta se aprueba (ALLOW) o rechaza (DENY).
   - El adapter NUNCA ejecuta por sí mismo.

3. CONFINAMIENTO DE OPERACIONES:
   - Prohibida la ejecución de comandos de shell del sistema.
   - Prohibido el acceso al filesystem fuera del entorno del sandbox temporal.
   - Prohibido el acceso a credenciales, variables de entorno sensibles y memoria del Core.
   - Prohibida la mutación de la configuración de JESSYCA.
```

```text
=====================================================
ORCA + ADE SECURITY AUDIT VERDICT
=====================================================
NATIVE THREAT LEVEL: HIGH (due to unrestricted shell execution)
JESSYCA MITIGATION: LAB ISOLATION + JDE SINGLE AUTHORITY
STATUS: PASS FOR LAB (with strict governance gates)
STATUS FOR PRODUCTION: BLOCKED (as mandated by Rule 0)
=====================================================
```
