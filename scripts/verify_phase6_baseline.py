import os
import sys
import shutil
import datetime
import json
import urllib.request
import sqlite3

print("=== 1. ENTORNO Y SISTEMA ===")
print("Python:", sys.version)
print("CWD:", os.getcwd())

print("\n=== 2. CREACIÓN DE RESPALDO VERIFICABLE ===")
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = os.path.join("backups", f"fase6_pre_integration_{ts}")
os.makedirs(backup_dir, exist_ok=True)
if os.path.exists("data"):
    shutil.copytree("data", os.path.join(backup_dir, "data"), dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.log", "*.tmp"))
if os.path.exists("config"):
    shutil.copytree("config", os.path.join(backup_dir, "config"), dirs_exist_ok=True)
print(f"Respaldo creado con éxito en: {backup_dir}")

print("\n=== 3. BASES DE DATOS DE MEMORIA ===")
for db_path in ["data/sessions.db", "data/memory_brain.db"]:
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall()]
            conn.close()
            print(f"- {db_path}: {size} bytes | Tablas: {tables}")
        except Exception as e:
            print(f"- {db_path}: Error al leer: {e}")
    else:
        print(f"- {db_path}: No existe aún")

print("\n=== 4. DISPONIBILIDAD DE OLLAMA Y MODELOS ===")
try:
    req = urllib.request.Request("http://localhost:11434/api/tags")
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode())
        models = [m.get("name") for m in data.get("models", [])]
        print("Ollama: DISPONIBLE")
        print("Modelos instalados:", models)
except Exception as e:
    print("Ollama: NO DISPONIBLE O ERROR:", e)

try:
    req = urllib.request.Request("http://localhost:11434/api/ps")
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode())
        running_models = data.get("models", [])
        print("Modelos en VRAM/RAM:", running_models)
except Exception as e:
    print("Ollama ps:", e)

print("\n=== 5. CONFIGURACIÓN DE VOZ, AUDIO Y HARDWARE ===")
try:
    from config.settings import settings
    print("OLLAMA_MODEL:", getattr(settings, "OLLAMA_MODEL", None))
    print("OLLAMA_HOST:", getattr(settings, "OLLAMA_HOST", None))
    print("TTS_ENGINE:", getattr(settings, "TTS_ENGINE", None))
    print("VOICE_NAME:", getattr(settings, "VOICE_NAME", None))
    print("STT_ENGINE:", getattr(settings, "STT_ENGINE", None))
    print("USE_JESSYCA_BRAIN (config):", getattr(settings, "USE_JESSYCA_BRAIN", False))
except Exception as e:
    print("Error al leer settings:", e)

print("\n=== 6. DISPOSITIVOS DE AUDIO (PYAUDIO/SOUNDDEVICE) ===")
try:
    import sounddevice as sd
    devices = sd.query_devices()
    default_in = sd.default.device[0]
    default_out = sd.default.device[1]
    print(f"Dispositivo de entrada por defecto: {devices[default_in]['name'] if default_in is not None and default_in < len(devices) else 'Ninguno'}")
    print(f"Dispositivo de salida por defecto: {devices[default_out]['name'] if default_out is not None and default_out < len(devices) else 'Ninguno'}")
except Exception as e:
    print("Audio query:", e)

print("\n=== 7. PROCESOS JESSYCA ACTIVOS ===")
try:
    import psutil
    jessyca_procs = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(p.info['cmdline'] or [])
            if "jessyca" in cmd.lower() or "main.py" in cmd.lower():
                jessyca_procs.append((p.info['pid'], p.info['name'], cmd[:80]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    print("Procesos activos de JESSYCA:", jessyca_procs)
except Exception as e:
    print("psutil check:", e)
