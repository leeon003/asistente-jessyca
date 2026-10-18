"""Parse explicit local paths before generic dance/YouTube heuristics."""
from pathlib import PureWindowsPath
import re


def resolve_local_media_request(text, dance_directory):
    lower = text.lower()
    path_match = re.search(r'([a-zA-Z]:[\\/][^"\r\n]*)', text)
    path = path_match.group(1).strip().rstrip('"') if path_match else None
    is_folder = bool(re.search(r'\b(?:abre|abrir|muestra)\s+(?:la\s+)?(?:carpeta|directorio)', lower))
    is_play = bool(re.search(r'\b(?:reproduce|reproducir|pon|ponme|toca)\b', lower))
    is_audio = any(word in lower for word in ('música', 'musica', 'audio', 'canción', 'cancion'))
    local = bool(path) or any(word in lower for word in ('carpeta', 'local', 'mi computadora', 'mi pc', 'disco'))
    if is_folder:
        folder = path or (str(dance_directory) if 'baile' in lower else None)
        if folder:
            return 'open_folder', {'target_folder': folder, 'app_name': 'explorer', 'accion': 'abrir_carpeta'}
        return 'clarification_needed', {'question': '¿Cuál es la ruta de la carpeta que quieres abrir?'}
    if not is_play or not local or 'youtube' in lower:
        return None
    path = path or (str(dance_directory) if 'baile' in lower else None)
    if not path:
        return 'clarification_needed', {'question': '¿En qué carpeta están los archivos que quieres reproducir?'}
    windows_path = PureWindowsPath(path)
    if windows_path.suffix.lower() in {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma'}:
        is_audio = True
    params = {'action': 'play_local_music' if is_audio else 'play_local_media',
              'target_directory': str(windows_path.parent if windows_path.suffix else windows_path),
              'media_type': 'audio' if is_audio else 'video', 'is_local_media': True}
    if windows_path.suffix:
        params['file_path'] = str(windows_path)
    return params['action'], params
