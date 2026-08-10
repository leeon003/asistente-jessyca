# Frontera de Seguridad PowerShell & CMD — Jessyca Windows MCP (Subetapa 07.3)

## Visión General

La **Subetapa 07.3** implementa las fronteras de seguridad dedicadas para entornos de consola PowerShell y CMD (`PowerShellExecutionBoundary`, `CMDExecutionBoundary`, `PowerShellInvocation`, `CMDInvocation`, `ExecutionBoundaryDecision`).

Esta subetapa es **ESTRICTAMENTE BOUNDARY & INVOCATION CONSTRUCTION ONLY**. No realiza ninguna ejecución de procesos.

---

## GARANTÍA ABSOLUTA: CERO EJECUCIÓN EN 07.3

1. **BOUNDARY ONLY**: Se realiza exclusivamente la validación de parámetros, filtrado de flags de bypass, bloqueo de obfuscación y construcción de la invocación inmutable.
2. **CERO SHELL / EXTERNAL EXECUTION**:
   - **NO** se utiliza `subprocess`
   - **NO** se utiliza `asyncio.create_subprocess_exec`
   - **NO** se utiliza `os.system`
   - **NO** se utiliza `os.popen`
   - **NO** se utiliza `cmd.exe`
   - **NO** se utiliza `powershell.exe`
   - **NO** se utiliza `shell=True`
   - **NO** se utiliza `eval` ni `exec`

La ejecución real de procesos mediante listas explícitas de argumentos está reservada exclusivamente para la Subetapa 07.4 (`CommandExecutionEngine`).

---

## Componentes Principales

### 1. `PowerShellExecutionBoundary`
- Valida el ejecutable contra `POWERSHELL_ALLOWED_EXECUTABLES`.
- Bloquea flags prohibidas de bypass: `-EncodedCommand`, `-Encoded`, `-ExecutionPolicy Bypass`, `-ExecutionPolicy Unrestricted`, `-Command`, `-c`, `-CommandWithArgs`, `-NoExit`, `-WindowStyle Hidden`.
- Impone banderas obligatorias de aislamiento: `-NoProfile`, `-NonInteractive`.
- Detección determinista de ejecución dinámica y obfuscación (`Invoke-Expression`, `iex`, `Start-Process`, `New-Object`, `Add-Type`, `System.Reflection`, `DownloadString`, `DownloadFile`).
- Binding criptográfico SHA-256 `action_fingerprint`.

### 2. `CMDExecutionBoundary`
- Valida el ejecutable contra `CMD_ALLOWED_EXECUTABLES`.
- Bloquea banderas de delegación arbitraria: `/c`, `/k`, `/s`.
- Bloquea metacarácteres y operadores de CMD: `&`, `&&`, `|`, `||`, `;`, `>`, `>>`, `<`, `<<`, `^`, `%`, `!`.
- Bloquea anidación de intérpretes de shell (`cmd /c powershell.exe`, etc.).
- Binding criptográfico SHA-256 `action_fingerprint`.

### 3. Modelos Inmutables (`dataclass(frozen=True)`)
`PowerShellInvocation`, `CMDInvocation`, `ExecutionBoundaryDecision`.
