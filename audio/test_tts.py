"""
audio/test_tts.py
Script de prueba para el módulo de síntesis de voz (TTS).
Ejecutar directamente con:
    python -m audio.test_tts
    o
    python audio/test_tts.py
"""
import sys
import os

# Asegurar que el directorio raíz del proyecto esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.tts import hablar

if __name__ == "__main__":
    print("Probando módulo de voz (TTS)...")
    exito = hablar("Hola jefecito, soy Jessyca")
    if exito:
        print("Prueba de voz completada con éxito.")
    else:
        print("La prueba de voz falló o no pudo conectarse al servicio TTS.")
