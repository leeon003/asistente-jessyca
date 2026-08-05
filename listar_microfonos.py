"""
listar_microfonos.py
Script utilitario temporal para listar los dispositivos de entrada de audio (micrófonos)
disponibles en el sistema mediante sounddevice.
"""
import sounddevice as sd


def listar_microfonos():
    print("=" * 65)
    print("    DISPOSITIVOS DE ENTRADA DE AUDIO (MICROFONOS) DISPONIBLES")
    print("=" * 65)

    try:
        devices = sd.query_devices()
        default_input = sd.default.device[0]

        encontrados = False
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                es_default = " -> [PREDETERMINADO]" if idx == default_input else ""
                print(f"Indice {idx:2d} | Canales: {dev['max_input_channels']} | Nombre: {dev['name']}{es_default}")
                encontrados = True

        if not encontrados:
            print("No se encontro ningun dispositivo de entrada de audio.")

    except Exception as e:
        print(f"Error al listar los dispositivos de audio: {e}")

    print("=" * 65)


if __name__ == "__main__":
    listar_microfonos()
