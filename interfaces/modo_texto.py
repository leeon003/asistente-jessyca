"""interfaces/modo_texto.py
Loop de interfaz de texto para interactuar con Jessyca por teclado.
Ejecutar con:
    python -m interfaces.modo_texto
"""
from __future__ import annotations

import sys

# Asegurar encoding UTF-8 en consola Windows si es posible
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.local_agent.local_agent import JessycaLocalAgent
from core.orquestador import ejecutar_orden_texto

BANNER = r"""
  +===============================================================+
  |                 J E S S Y C A   3 . 0                         |
  |               Agente Local e Inteligente                      |
  |  Escribe tu orden o consulta. Escribe "salir" para terminar.  |
  +===============================================================+
"""


def iniciar_modo_texto() -> None:
    print(BANNER)
    try:
        agent = JessycaLocalAgent.get_instance()
    except Exception:
        agent = None

    while True:
        try:
            texto = input("\n  Tú: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  Jessyca: ¡Hasta luego! Que tengas un excelente día.")
            break

        if not texto:
            continue

        if texto.lower() in ("salir", "exit", "quit", "adios", "adiós"):
            print("\n  Jessyca: ¡Hasta luego! Que tengas un excelente día.")
            break

        if agent is not None:
            try:
                res = agent.interact(texto)
                if res.requires_clarification and res.clarification_question:
                    print(f"\n  Jessyca (Aclaración): {res.clarification_question}")
                elif res.requires_confirmation:
                    print(f"\n  Jessyca (Confirmación Requerida): {res.response_text}")
                    conf = input("  ¿Deseas confirmar esta acción peligrosa? (s/n): ").strip().lower()
                    if conf in ("s", "si", "sí", "y", "yes"):
                        res_conf = agent.interact(f"CONFIRMAR {res.request_id}")
                        print(f"\n  Jessyca: {res_conf.response_text}")
                    else:
                        print("\n  Jessyca: Acción cancelada por seguridad.")
                else:
                    print(f"\n  Jessyca: {res.response_text}")

                # Metadata informativa
                print(f"  [Intención: {res.intent} | Agente: {res.selected_agent} | Skill: {res.selected_skill} | Seguridad: {res.security_verdict}]")
            except Exception:
                respuesta = ejecutar_orden_texto(texto)
                print(f"\n  Jessyca: {respuesta}")
        else:
            respuesta = ejecutar_orden_texto(texto)
            print(f"\n  Jessyca: {respuesta}")


if __name__ == "__main__":
    iniciar_modo_texto()
