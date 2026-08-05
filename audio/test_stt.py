"""
audio/test_stt.py
Script de prueba para el módulo de reconocimiento de voz (STT).
Ejecutar directamente con:
    python audio/test_stt.py
"""
import sys
import os

# Asegurar que el directorio raíz del proyecto esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.stt import escuchar

if __name__ == "__main__":
    print("Iniciando prueba del módulo STT (Speech-To-Text)...")
    texto = escuchar(duracion_segundos=5)
    
    if texto:
        print(f"\n[Transcripción exitosa]: \"{texto}\"")
    else:
        print("\n[Transcripción]: No se obtuvo ningún texto transcrito.")
