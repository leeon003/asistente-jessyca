import pyaudio
import os
import time

def check_audio_devices():
    p = pyaudio.PyAudio()
    print("=== DISPOSITIVOS DE AUDIO DETECTADOS EN WINDOWS 11 ===")
    mic_found = None
    speaker_found = None
    
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        name = dev.get("name", "")
        max_in = dev.get("maxInputChannels", 0)
        max_out = dev.get("maxOutputChannels", 0)
        host_api = dev.get("hostApi", -1)
        
        # Filtrar dispositivos con nombres legibles
        if max_in > 0 and ("g435" in name.lower() or "micr" in name.lower()):
            print(f"  [INPUT] Id {i}: {name} (Canales: {max_in}, HostAPI: {host_api})")
            if not mic_found or "g435" in name.lower():
                mic_found = (i, name)
        elif max_out > 0 and ("realtek" in name.lower() or "g435" in name.lower() or "altavoz" in name.lower()):
            print(f"  [OUTPUT] Id {i}: {name} (Canales: {max_out}, HostAPI: {host_api})")
            if not speaker_found:
                speaker_found = (i, name)
                
    p.terminate()
    print("\nResumen de Resolución:")
    print(f"  Micrófono seleccionado: {mic_found}")
    print(f"  Altavoces seleccionados: {speaker_found}")
    return mic_found, speaker_found

if __name__ == "__main__":
    check_audio_devices()
