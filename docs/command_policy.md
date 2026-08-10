# Política de Comandos y Fundación de Lista Blanca — Jessyca Windows MCP (Subetapa 07.1)

## Visión General

La **Subetapa 07.1** establece la capa declarativa de políticas y listas blancas (`CommandPolicyManager`, `CommandAllowlistRule`, `CommandRiskClassifier`) para el futuro dominio de consola `windows.shell`.

Esta subetapa es **ESTRICTAMENTE POLICY-ONLY / METADATA-ONLY**. No realiza ninguna ejecución de procesos.

---

## GARANTÍA ABSOLUTA: CERO EJECUCIÓN EN 07.1

1. **METADATA-ONLY**: Se realiza únicamente la evaluación declarativa de reglas de lista blanca y clasificación de riesgo.
2. **CERO SHELL / EXTERNAL EXECUTION**:
   - **NO** se utiliza `subprocess`
   - **NO** se utiliza `asyncio.create_subprocess_exec`
   - **NO** se utiliza `os.system`
   - **NO** se utiliza `os.popen`
   - **NO** se utiliza `cmd.exe`
   - **NO** se utiliza `powershell.exe`
   - **NO** se utiliza `shell=True`

La ejecución real de procesos mediante listas explícitas de argumentos está reservada exclusivamente para la Subetapa 07.4.

---

## Componentes Principales

### 1. `CommandAllowlistRule` (`dataclass(frozen=True)`)
Modelo inmutable que define las reglas de ejecutables y argumentos autorizados (`git`, `dir`, `echo`, `ipconfig`, `systeminfo`).

### 2. `ShellMetacharacterDetector`
Filtra y rechaza metacarácteres peligrosos de shell: `&`, `|`, `;`, `` ` ``, `$()`, `)`, `>`, `<`, `&&`, `||`.

### 3. `CommandRiskClassifier`
Clasifica deterministamente el riesgo del comando. Aplica la invariante **`UNKNOWN -> DENY`**.

### 4. `CommandPolicyManager`
Gestor thread-safe y sellable (`lock_registry()`) que evalúa los comandos y aplica la regla `most_restrictive`.
