bat_content = """@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
title JESSYCA BRAIN 1.0 — Asistente Personal Windows 11

:: 1. Garantizar que el directorio de trabajo sea la carpeta del proyecto
cd /d "%~dp0"

echo =========================================================================
echo       JESSYCA BRAIN 1.0 — ASISTENTE PERSONAL (WINDOWS 11)
echo =========================================================================
echo [INFO] Carpeta de instalacion: %CD%

:: 2. Deteccion automatica del interprete Python 3.11
set "PYTHON_EXE="

:: Probar Python 3.11 en AppData de usuario
if not defined PYTHON_EXE (
    if exist "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe" (
        "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe" -c "import core.local_agent" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe"
            echo [OK] Python 3.11 verificado en AppData
        )
    )
)

:: Probar python global en PATH
if not defined PYTHON_EXE (
    python -c "import core.local_agent" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
        echo [OK] Python detectado en PATH con dependencias del proyecto
    )
)

:: Probar entorno virtual local venv si tiene dependencias
if not defined PYTHON_EXE (
    if exist "%~dp0venv\\Scripts\\python.exe" (
        "%~dp0venv\\Scripts\\python.exe" -c "import core.local_agent" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=%~dp0venv\\Scripts\\python.exe"
            echo [OK] Entorno virtual detectado: venv
        )
    )
)

:: Probar py launcher
if not defined PYTHON_EXE (
    py -3.11 -c "import core.local_agent" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py -3.11"
        echo [OK] Python 3.11 detectado via py launcher
    )
)

:: Si no se encontro ningun Python valido
if not defined PYTHON_EXE (
    echo.
    echo =========================================================================
    echo [ERROR CRITICO] No se encontro un interprete Python con dependencias.
    echo Por favor ejecuta la instalacion de dependencias requeridas para JESSYCA.
    echo =========================================================================
    echo.
    echo Presione cualquier tecla para salir...
    pause >nul
    exit /b 1
)

:: 3. Verificar si Ollama esta respondiendo
echo [INFO] Comprobando servidor Ollama en localhost:11434...
curl -s http://localhost:11434/api/tags >nul 2>&1
if !errorlevel! neq 0 (
    echo [AVISO] Servidor Ollama no detectado en localhost:11434.
    echo Intentando iniciar 'ollama serve' en segundo plano...
    start /min "" ollama serve
    timeout /t 2 /nobreak >nul
)

:: 4. Ejecutar el punto de entrada oficial
echo [INFO] Iniciando JESSYCA BRAIN 1.0...
echo.
"%PYTHON_EXE%" "%~dp0iniciar_jessyca.py" %*
set "EXIT_CODE=%errorlevel%"

if %EXIT_CODE% neq 0 (
    echo.
    echo =========================================================================
    echo [ERROR] JESSYCA finalizo con codigo de salida: %EXIT_CODE%
    echo Puedes consultar los detalles y la traza en: logs\\startup.log
    echo =========================================================================
) else (
    echo.
    echo JESSYCA se cerro correctamente.
)

:: 5. Mantener la ventana abierta tras la ejecucion
echo.
echo Presione cualquier tecla para cerrar esta ventana...
pause >nul
exit /b %EXIT_CODE%
"""

crlf_content = bat_content.replace("\r\n", "\n").replace("\n", "\r\n")
with open("iniciar_jessyca.bat", "wb") as f:
    f.write(crlf_content.encode("utf-8"))
print("iniciar_jessyca.bat saved with CRLF line endings.")
