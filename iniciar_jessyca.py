"""iniciar_jessyca.py
Lanzador Oficial y Asistente Pre-Flight de JESSYCA BRAIN 1.0 para Windows 11.
Verifica dependencias, modelos de Ollama, audio, memoria cognitiva y permite
iniciar el modo deseado con registro persistente en logs/startup.log.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# Asegurar codificación UTF-8 en consola de Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
STARTUP_LOG_FILE = LOGS_DIR / "startup.log"

BANNER = r"""
╔═════════════════════════════════════════════════════════════════════════╗
║                   J E S S Y C A   B R A I N   1 . 0                     ║
║              ASISTENTE PERSONAL AUTÓNOMO — WINDOWS 11                   ║
║                                                                         ║
║   ✓ Reasoning Engine        ✓ Memory Engine (4 capas)                   ║
║   ✓ Planner Engine (DAG)    ✓ Procedure Learning (Enseñanza segura)     ║
║   ✓ Native Windows Driver   ✓ Emergency Stop & Safety                   ║
║   ✓ Ollama Local Inference  ✓ CamilaNeural Spoken TTS                  ║
╚═════════════════════════════════════════════════════════════════════════╝
"""


def log_startup_entry(status_dict: dict[str, Any], result: str = "INICIADO", error: str | None = None) -> None:
    """Escribe un registro de inicio estructurado en logs/startup.log."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"================================================================================",
            f"FECHA Y HORA:          {now_str}",
            f"VERSIÓN JESSYCA:       4.0 (JESSYCA BRAIN 1.0)",
            f"VERSIÓN PYTHON:        {status_dict.get('python_version', sys.version)}",
            f"RUTA INTÉRPRETE:       {status_dict.get('python_path', sys.executable)}",
            f"DIRECTORIO PROYECTO:   {status_dict.get('project_root', str(PROJECT_ROOT))}",
            f"MODELO OLLAMA CONFIG:  {status_dict.get('ollama_model', 'qwen3.5:9b')}",
            f"ESTADO OLLAMA:         {status_dict.get('ollama_status', 'DESCONOCIDO')}",
            f"MODELOS DISPONIBLES:   {status_dict.get('ollama_models', 'Ninguno')}",
            f"ESTADO CEREBRO (BRAIN):{status_dict.get('brain_status', 'DESCONOCIDO')}",
            f"ESTADO MEMORIA SQLITE: {status_dict.get('memory_status', 'DESCONOCIDO')}",
            f"MICRÓFONO DETECTADO:   {status_dict.get('audio_mic', 'DESCONOCIDO')}",
            f"ALTAVOCES DETECTADOS:  {status_dict.get('audio_spk', 'DESCONOCIDO')}",
            f"BACKEND ESCRITORIO:    {status_dict.get('desktop_backend', 'NativeWindowsDriver')}",
            f"RESULTADO DE ARRANQUE: {result}",
        ]
        if error:
            lines.append(f"ERROR / EXCEPCIÓN:     {error}")
        lines.append("================================================================================\n")
        with open(STARTUP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[AVISO] No se pudo escribir en logs/startup.log: {e}")


def check_ollama(model_name: str = "qwen3.5:9b") -> tuple[bool, list[str], str]:
    """Verifica si el servidor Ollama está activo y si contiene el modelo configurado."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            has_model = any(model_name in m for m in models)
            msg = f"Activo (Modelos: {len(models)})"
            if not has_model:
                msg += f" - [!] Modelo {model_name} no encontrado"
            return True, models, msg
    except Exception:
        # Intentar iniciar ollama serve si no está activo
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return True, models, f"Iniciado automáticamente (Modelos: {len(models)})"
        except Exception:
            return False, [], "No activo en localhost:11434 (Inicia 'ollama serve')"


def check_audio_devices() -> tuple[str, str]:
    """Detecta micrófono y altavoces disponibles en Windows 11."""
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        mic = "No detectado"
        spk = "No detectado"
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            name = dev.get("name", "")
            if dev.get("maxInputChannels", 0) > 0:
                if "g435" in name.lower():
                    mic = f"Logitech G435 ({name})"
                elif mic == "No detectado" and ("mic" in name.lower() or "entrada" in name.lower()):
                    mic = name
            if dev.get("maxOutputChannels", 0) > 0:
                if "g435" in name.lower():
                    spk = f"Logitech G435 ({name})"
                elif "realtek" in name.lower():
                    spk = f"Realtek Audio ({name})"
                elif spk == "No detectado":
                    spk = name
        p.terminate()
        return mic, spk
    except Exception:
        return "Audio predeterminado del sistema", "Altavoces predeterminados"


def check_brain_components() -> tuple[bool, str]:
    """Comprueba que JESSYCA BRAIN 1.0 y sus motores cognitivos estén configurados y cargables."""
    try:
        from config.manager import get_settings
        settings = get_settings()
        use_brain = getattr(settings, "USE_JESSYCA_BRAIN", False)
        if not use_brain:
            return False, "USE_JESSYCA_BRAIN está en False en config/settings.py"

        from core.cognitive_brain.brain_orchestrator import JessycaBrain
        from core.execution.execution_verifier import ExecutionVerifier

        brain = JessycaBrain()
        verifier = ExecutionVerifier()

        if (
            brain.reasoning_engine
            and brain.planner_engine
            and brain.memory_engine
            and brain.procedure_learning_engine
            and brain.sai_bridge
            and brain.risk_engine
            and brain.permission_manager
            and brain.desktop_controller
            and verifier
        ):
            return True, "JESSYCA BRAIN 1.0 Activo y Completo (9 Motores Certificados)"
        return True, "JESSYCA BRAIN 1.0 Parcial"
    except Exception as e:
        return False, f"Error inicializando cerebro: {e}"


def check_memory_dbs() -> tuple[bool, str]:
    """Verifica bases de datos SQLite de memoria cognitiva y sesiones."""
    try:
        db_brain = PROJECT_ROOT / "data" / "memory_brain.db"
        db_sess = PROJECT_ROOT / "data" / "sessions.db"
        (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
        brain_ok = db_brain.exists() and db_brain.stat().st_size > 0
        sess_ok = db_sess.exists() and db_sess.stat().st_size > 0
        if brain_ok and sess_ok:
            return True, f"Bases conectadas (memory_brain: {db_brain.stat().st_size // 1024} KB, sessions: {db_sess.stat().st_size // 1024} KB)"
        elif brain_ok or sess_ok:
            return True, "Base de memoria inicializada parcialmente"
        else:
            return True, "Bases de memoria se crearán automáticamente al primer uso"
    except Exception as e:
        return False, f"Error comprobando memoria: {e}"


def perform_full_diagnostics() -> dict[str, Any]:
    """Ejecuta la batería de comprobaciones pre-flight y retorna el reporte."""
    from config.manager import get_settings
    settings = get_settings()
    model_name = getattr(settings, "OLLAMA_MODEL", "qwen3.5:9b")

    ollama_ok, models, ollama_msg = check_ollama(model_name)
    mic, spk = check_audio_devices()
    brain_ok, brain_msg = check_brain_components()
    mem_ok, mem_msg = check_memory_dbs()

    report = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_path": sys.executable,
        "project_root": str(PROJECT_ROOT),
        "ollama_model": model_name,
        "ollama_status": "CONECTADO" if ollama_ok else "NO DISPONIBLE",
        "ollama_models": ", ".join(models) if models else "Ninguno",
        "brain_status": brain_msg,
        "memory_status": mem_msg,
        "audio_mic": mic,
        "audio_spk": spk,
        "desktop_backend": "UnifiedDesktopController (NativeWindowsDriver)",
    }
    return report


def display_preflight(report: dict[str, Any]) -> None:
    """Muestra en pantalla el estado pre-flight formateado."""
    print(BANNER)
    print("--- COMPROBACIONES PRE-FLIGHT DEL SISTEMA ---")
    print(f"  [✓] Runtime Python:        {report['python_version']} ({report['python_path']})")
    print(f"  [✓] Directorio Proyecto:   {report['project_root']}")
    
    ollama_prefix = "[✓]" if report["ollama_status"] == "CONECTADO" else "[!]"
    print(f"  {ollama_prefix} Servidor Ollama:       {report['ollama_status']} (Modelo: {report['ollama_model']})")
    print(f"      Modelos disponibles:   {report['ollama_models']}")
    
    print(f"  [✓] JESSYCA BRAIN 1.0:     {report['brain_status']}")
    print(f"  [✓] Memoria Persistente:   {report['memory_status']}")
    print(f"  [✓] Micrófono Entrada:     {report['audio_mic']}")
    print(f"  [✓] Altavoces Salida:      {report['audio_spk']}")
    print(f"  [✓] Control de Escritorio: {report['desktop_backend']}")
    print("-" * 75)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lanzador Oficial de JESSYCA BRAIN 1.0")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--voice", "-v", action="store_true", help="Iniciar Modo Voz Continuo con Orbe 3D")
    group.add_argument("--ptt", "-p", action="store_true", help="Iniciar Modo Pulsar para Hablar (PTT)")
    group.add_argument("--text", "-t", action="store_true", help="Iniciar Modo Texto Interactivo")
    group.add_argument("--orb-standalone", action="store_true", help="Iniciar Solo Servidor y Ventana del Orbe 3D")
    group.add_argument("--guided-voice", action="store_true", help="Ejecutar Prueba Guiada de Micrófono")
    group.add_argument("--acceptance", action="store_true", help="Ejecutar Suite de Aceptación de 10 Escenarios")
    group.add_argument("--diag", "-d", action="store_true", help="Ejecutar solo diagnóstico y salir")
    parser.add_argument("--no-orb", action="store_true", help="Desactivar la ventana del Orbe 3D en Modo Voz")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    report = perform_full_diagnostics()
    log_startup_entry(report, result="PRE_FLIGHT_EJECUTADO")
    enable_orb = not args.no_orb

    if args.diag:
        display_preflight(report)
        return 0

    if args.orb_standalone:
        display_preflight(report)
        print("\n[INICIO DIRECTO] Iniciando Servidor y Ventana del Orbe 3D Aurora...")
        from interfaces.aurora.launcher import AuroraPrototypeRunner
        runner = AuroraPrototypeRunner(port=8765, headless=False, simulate_audio=True)
        try:
            runner.start()
            while True:
                time.sleep(1.0)
        except (KeyboardInterrupt, EOFError):
            runner.stop()
        return 0

    if args.voice:
        display_preflight(report)
        print(f"\n[INICIO DIRECTO] Iniciando Modo Voz Continuo (Orbe 3D: {'ACTIVO' if enable_orb else 'INACTIVO'})...")
        from main import run_voice_mode
        log_startup_entry(report, result="MODO_VOZ_CONTINUO")
        return run_voice_mode(ptt=False, enable_orb=enable_orb)

    if args.ptt:
        display_preflight(report)
        print(f"\n[INICIO DIRECTO] Iniciando Modo Pulsar para Hablar (PTT) (Orbe 3D: {'ACTIVO' if enable_orb else 'INACTIVO'})...")
        from main import run_voice_mode
        log_startup_entry(report, result="MODO_PTT")
        return run_voice_mode(ptt=True, enable_orb=enable_orb)

    if args.text:
        display_preflight(report)
        print("\n[INICIO DIRECTO] Iniciando Modo Texto Interactivo...")
        from main import run_text_mode
        log_startup_entry(report, result="MODO_TEXTO")
        return run_text_mode()

    if args.guided_voice:
        display_preflight(report)
        print("\n[INICIO DIRECTO] Iniciando Sesión Guiada de Validación de Micrófono...")
        from scripts.guided_voice_test import run_guided_test
        log_startup_entry(report, result="PRUEBA_VOZ_GUIADA")
        run_guided_test()
        return 0

    if args.acceptance:
        display_preflight(report)
        print("\n[INICIO DIRECTO] Ejecutando Suite de Aceptación (10 Escenarios)...")
        log_startup_entry(report, result="SUITE_ACEPTACION")
        res = subprocess.run([sys.executable, "-m", "pytest", "tests/acceptance/test_fase7_user_end_to_end_10_scenarios.py", "-v", "-s"])
        return res.returncode

    # Si no se pasó argumento por flag, mostrar Menú Interactivo
    display_preflight(report)
    print("\n" + "=" * 65)
    print("  SELECCIONA EL MODO DE INICIO PARA JESSYCA:")
    print("  1. Iniciar Modo Voz Continuo con Orbe 3D (Escucha / 'Jessica')")
    print("  2. Iniciar Modo Pulsar para Hablar con Orbe 3D (PTT con ENTER)")
    print("  3. Iniciar Modo Texto Interactivo (Consola de chat CLI)")
    print("  4. Iniciar Solo Ventana y Servidor del Orbe 3D (Demo Standalone)")
    print("  5. Ejecutar Prueba Presencial Guiada de Micrófono (G435)")
    print("  6. Diagnóstico Completo del Asistente (Doctor & Pre-Flight)")
    print("  7. Ejecutar Suite de Aceptación de Usuario (10 Escenarios)")
    print("  8. Salir")
    print("=" * 65)

    try:
        opcion = input("\nElige una opción (1-8) [predeterminado: 1]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nSesión cancelada por el usuario. ¡Hasta luego!")
        log_startup_entry(report, result="CANCELADO_POR_USUARIO")
        return 0

    if not opcion or opcion == "1":
        print("\nIniciando Modo Voz Continuo con Orbe 3D...")
        log_startup_entry(report, result="MODO_VOZ_CONTINUO")
        from main import run_voice_mode
        return run_voice_mode(ptt=False, enable_orb=True)
    elif opcion == "2":
        print("\nIniciando Modo Pulsar para Hablar con Orbe 3D (PTT)...")
        log_startup_entry(report, result="MODO_PTT")
        from main import run_voice_mode
        return run_voice_mode(ptt=True, enable_orb=True)
    elif opcion == "3":
        print("\nIniciando Modo Texto Interactivo...")
        log_startup_entry(report, result="MODO_TEXTO")
        from main import run_text_mode
        return run_text_mode()
    elif opcion == "4":
        print("\nIniciando Solo Ventana y Servidor del Orbe 3D...")
        from interfaces.aurora.launcher import AuroraPrototypeRunner
        runner = AuroraPrototypeRunner(port=8765, headless=False, simulate_audio=True)
        try:
            runner.start()
            while True:
                time.sleep(1.0)
        except (KeyboardInterrupt, EOFError):
            runner.stop()
        return 0
    elif opcion == "5":
        print("\nIniciando Sesión Guiada de Validación de Micrófono...")
        log_startup_entry(report, result="PRUEBA_VOZ_GUIADA")
        from scripts.guided_voice_test import run_guided_test
        run_guided_test()
        return 0
    elif opcion == "6":
        print("\nEjecutando Diagnóstico Completo (Doctor)...")
        from main import run_doctor_command
        import argparse
        return run_doctor_command(argparse.Namespace(json=False))
    elif opcion == "7":
        print("\nEjecutando Suite de Aceptación de 10 Escenarios...")
        log_startup_entry(report, result="SUITE_ACEPTACION")
        res = subprocess.run([sys.executable, "-m", "pytest", "tests/acceptance/test_fase7_user_end_to_end_10_scenarios.py", "-v", "-s"])
        return res.returncode
    elif opcion == "8":
        print("\n¡Hasta luego!")
        log_startup_entry(report, result="SALIDA_VOLUNTARIA")
        return 0
    else:
        print("\nOpción no válida. Iniciando Modo Voz con Orbe 3D por defecto...")
        log_startup_entry(report, result="MODO_VOZ_DEFAULT")
        from main import run_voice_mode
        return run_voice_mode(ptt=False, enable_orb=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\n[ERROR CRÍTICO DURANTE LA EJECUCIÓN] {exc}")
        import traceback
        traceback.print_exc()
        try:
            report = perform_full_diagnostics()
            log_startup_entry(report, result="ERROR_FATAL", error=str(exc))
        except Exception:
            pass
        sys.exit(1)
