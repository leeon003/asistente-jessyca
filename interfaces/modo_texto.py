"""interfaces/modo_texto.py
Loop de interfaz de texto para interactuar con Jessyca por teclado.
Ejecutar con:
    python -m interfaces.modo_texto
"""
from core.orquestador import ejecutar_orden_texto


BANNER = r"""
  ╔══════════════════════════════════════╗
  ║    J E S S Y C A  —  Modo Texto     ║
  ║  Escribe tu orden. "salir" para fin. ║
  ╚══════════════════════════════════════╝
"""


def iniciar_modo_texto() -> None:
    print(BANNER)
    while True:
        try:
            texto = input("  Tú: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Jessyca: ¡Hasta luego!")
            break

        if not texto:
            continue

        if texto.lower() in ("salir", "exit", "quit", "adios", "adiós"):
            print("  Jessyca: ¡Hasta luego!")
            break

        respuesta = ejecutar_orden_texto(texto)
        print(f"\n  Jessyca: {respuesta}\n")


if __name__ == "__main__":
    iniciar_modo_texto()
