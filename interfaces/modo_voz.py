"""
interfaces/modo_voz.py
Interfaz de voz completa para interactuar con Jessyca de forma manos libres.

Flujo del loop continuo:
1. Escuchar en segundo plano hasta detectar la palabra clave "Jessyca" (Wake Word).
2. Responder por voz: "Dime, jefecito".
3. Grabar la orden del usuario con STT.
4. Procesar la orden con el orquestador (ejecutar_orden_texto).
5. Responder por voz con TTS el resultado de la orden.
6. Ventana de escucha activa (5s): Preguntar "¿Necesitas algo más, jefecito?" y escuchar directamente con STT.
   - Si dice una nueva orden: Procesar y continuar la conversación.
   - Si no habla (silencio) o dice "no" / "nada más" / "gracias": Volver a la espera de la palabra clave.
"""
import sys
import logging
from audio.wake_word import esperar_wake_word
from audio.tts import hablar
from audio.stt import escuchar
from core.orquestador import ejecutar_orden_texto

logger = logging.getLogger(__name__)

# Asegurar codificación UTF-8 en salida estándar para consolas Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BANNER_VOZ = r"""
  ╔══════════════════════════════════════════╗
  ║      J E S S Y C A  —  Modo Voz          ║
  ║  Di "Jessyca" para activar el asistente  ║
  ║  Presiona Ctrl+C para finalizar.         ║
  ╚══════════════════════════════════════════╝
"""

FRASES_CIERRE = {
    "no", "nada", "nada mas", "nada más", "gracias", "listo", "fin",
    "adios", "adiós", "todo bien", "ninguna", "ninguno", "no gracias"
}


def iniciar_modo_voz() -> None:
    """Inicia el loop continuo de voz con ventana de escucha activa conversacional."""
    print(BANNER_VOZ)

    while True:
        try:
            # 1. Esperar a que el usuario diga "Jessyca" (Wake Word)
            esperar_wake_word()

            # 2. Confirmación auditiva de activación
            print("\n[Jessyca Voz]: Dime, jefecito.")
            hablar("Dime, jefecito")

            # 3. Escuchar la primera orden del usuario con STT
            print("[Jessyca Voz]: Escuchando tu orden...")
            orden = escuchar(duracion_segundos=6)

            # Bucle de escucha activa (conversación continua sin requerir Wake Word de nuevo)
            while True:
                if not orden or not orden.strip():
                    print("[Jessyca Voz]: No se escuchó ninguna orden clara.")
                    hablar("No logré escucharte, jefecito.")
                    break

                print(f"\n  Tú (Voz): {orden}")

                # 4. Procesar la orden con el orquestador
                respuesta = ejecutar_orden_texto(orden)

                print(f"  Jessyca: {respuesta}\n")

                # 5. Responder el resultado por voz (TTS)
                hablar(respuesta)

                # 6. Ventana de escucha activa (5s) para preguntas de seguimiento
                print("\n[Jessyca Voz]: ¿Necesitas algo más, jefecito?")
                hablar("¿Necesitas algo más, jefecito?")

                print("[Jessyca Voz - Escucha Activa 5s]: Esperando tu respuesta...")
                seguimiento = escuchar(duracion_segundos=5)

                if not seguimiento or not seguimiento.strip():
                    print("[Jessyca Voz]: Silencio detectado en escucha activa. Volviendo a espera de palabra clave.")
                    break

                seguimiento_norm = seguimiento.strip().lower()
                palabras_seguimiento = set(seguimiento_norm.split())

                if seguimiento_norm in FRASES_CIERRE or palabras_seguimiento.intersection(FRASES_CIERRE):
                    print(f"  Tú (Voz): {seguimiento}")
                    print("  Jessyca: De nada, quedo atenta jefecito.\n")
                    hablar("De nada, quedo atenta jefecito.")
                    break

                # Si el usuario dio una orden nueva en la ventana activa, continuar el bucle directo
                orden = seguimiento

        except KeyboardInterrupt:
            print("\n\n  Jessyca: ¡Modo voz finalizado! Hasta luego, jefecito.")
            hablar("Hasta luego, jefecito.")
            break
        except Exception as e:
            mensaje_error = "Ocurrió un inconveniente al procesar tu solicitud."
            logger.error(f"[Modo Voz Error]: {e}")
            print(f"\n[Jessyca Voz Error]: {e}")
            hablar(mensaje_error)


if __name__ == "__main__":
    iniciar_modo_voz()
