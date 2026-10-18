import os
import sys

def test_playback():
    audio_file = "scratch/voice_tests/test_synthesis.mp3"
    if not os.path.exists(audio_file):
        print(f"Error: {audio_file} no existe.")
        return False
        
    print(f"Reproduciendo audio real en altavoces: {audio_file} ...")
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        pygame.mixer.quit()
        print("Reproducción con Pygame completada con éxito.")
        return True
    except Exception as e:
        print(f"Pygame fallo ({e}), intentando via PowerShell Media.SoundPlayer...")
        # Fallback a powershell
        cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{os.path.abspath(audio_file)}\').PlaySync()"'
        os.system(cmd)
        print("Reproducción completada.")
        return True

if __name__ == "__main__":
    test_playback()
