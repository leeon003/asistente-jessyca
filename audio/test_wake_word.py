"""
audio/test_wake_word.py
Script de prueba para la detección de palabra de activación "Jessyca".
Ejecutar con:
    python audio/test_wake_word.py
"""
import sys
import os

# Asegurar que el directorio raíz del proyecto esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.wake_word import esperar_wake_word

if __name__ == "__main__":
    print("Iniciando prueba de detección de palabra clave (Wake Word)...")
    esperar_wake_word()
    print("¡Activado!")
