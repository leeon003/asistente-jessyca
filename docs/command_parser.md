# Parser Seguro de Comandos y Tokenizador — Jessyca Windows MCP (Subetapa 07.2)

## Visión General

La **Subetapa 07.2** implementa el parser seguro y tokenizador determinista (`SecureCommandParser`, `CommandLexer`, `CommandArgumentValidator`, `StructuredCommand`) para transformar entradas de consola no confiables en listas explícitas de argumentos `[executable, arg1, arg2, ...]`.

Esta subetapa es **ESTRICTAMENTE PARSER-ONLY / TEXT ANALYSIS ONLY**. No realiza ninguna ejecución de procesos.

---

## GARANTÍA ABSOLUTA: CERO EJECUCIÓN EN 07.2

1. **PARSER-ONLY**: Se realiza exclusivamente el análisis léxico, tokenización y validación de argumentos.
2. **CERO SHELL / EXTERNAL EXECUTION**:
   - **NO** se utiliza `subprocess`
   - **NO** se utiliza `asyncio.create_subprocess_exec`
   - **NO** se utiliza `os.system`
   - **NO** se utiliza `os.popen`
   - **NO** se utiliza `cmd.exe`
   - **NO** se utiliza `powershell.exe`
   - **NO** se utiliza `shell=True`
   - **NO** se utiliza `eval` ni `exec`

La ejecución real de procesos mediante listas explícitas de argumentos está reservada exclusivamente para la Subetapa 07.4.

---

## Componentes Principales

### 1. `StructuredCommand` (`dataclass(frozen=True)`)
Modelo inmutable que contiene el ejecutable, argumentos, hash canónico SHA-256 (`raw_input_hash`), cantidad de argumentos y estado de validez.

### 2. `CommandLexer`
Tokenizador estado-máquina que maneja comillas dobles y simples (`"hello world"` -> `["echo", "hello world"]`), y rechaza inmediatamente operadores peligrosos de shell (`&`, `&&`, `|`, `||`, `;`, `` ` ``, `$()`, `>`, `>>`, `<`, `<<`), caracteres nulos (`\x00`) y saltos de línea (`\r`, `\n`).

### 3. `CommandArgumentValidator`
Validador de límites que enforza `COMMAND_MAX_ARGUMENTS` (50), `COMMAND_MAX_ARGUMENT_LENGTH` (1024), `COMMAND_MAX_TOTAL_LENGTH` (4096) y caracteres de control Unicode.

### 4. `SecureCommandParser`
Orquestador que genera `StructuredCommand` inmutable, calcula el hash SHA-256 canónico y emite eventos de auditoría sanitizados.
