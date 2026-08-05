# main.py — Punto de entrada principal del asistente Jessyca
# Modo Voz: integra Wake Word ("Jessyca") + STT + Orquestador + TTS

from interfaces.modo_voz import iniciar_modo_voz

if __name__ == "__main__":
    iniciar_modo_voz()
