"""Skill de reproducción multimedia de Windows (windows_media_skill.py - Smart Media Playback).

Implementa la capacidad gobernada de reproducción multimedia para JESSYCA 3.0:
    "Jessyca, báilame" / "play_random_video"

GARANTÍAS DE SEGURIDAD ABSOLUTAS:
1. ACCESO EXCLUSIVO: Opera únicamente sobre el directorio autorizado (por defecto D:\\bailes de ia).
2. NO SHELL ARBITRARIO: Cero uso de os.system(), eval(), exec() o shell=True con cadenas generadas por LLM.
3. CANONICALIZACIÓN Y ANTI-PATH TRAVERSAL: Verifica estrictamente que la ruta resuelta pertenezca al directorio autorizado.
4. FILTRADO ESTRICTO: Solo extensiones de vídeo autorizadas (.mp4, .mkv, .avi, .mov, .webm, .wmv, .m4v).
5. REGLA FUNDAMENTAL: 1 Petición -> 1 Vídeo -> 1 Lanzamiento -> 1 Verificación -> 1 Respuesta.
"""

from __future__ import annotations

import os
import json
import random
import subprocess
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from config.settings import AppSettings
from core.execution.execution_verifier import ExecutionEvidence, get_execution_verifier
from core.logger import get_logger
from core.media_playback import ManagedMediaPlayer
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.windows_media")

DEFAULT_AUTHORIZED_DANCE_DIRECTORY = Path(r"D:\bailes de ia")

SUPPORTED_VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".wmv",
    ".m4v",
})
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"})

DANGEROUS_EXTENSIONS: frozenset[str] = frozenset({
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".scr",
    ".msi",
    ".dll",
    ".com",
    ".pif",
    ".hta",
    ".cpl",
    ".jar",
    ".wsf",
})

KNOWN_MEDIA_PLAYER_PROCESSES: frozenset[str] = frozenset({
    "wmplayer.exe",
    "wmplayer",
    "vlc.exe",
    "vlc",
    "mpc-hc.exe",
    "mpc-hc64.exe",
    "mpc-be.exe",
    "mpc-be64.exe",
    "potplayer.exe",
    "potplayermini64.exe",
    "video.ui.exe",
    "applicationframehost.exe",
    "movies.exe",
})


@runtime_checkable
class IMediaPlayer(Protocol):
    """Interfaz abstracta del reproductor multimedia del sistema."""

    def launch(self, video_path: Path) -> tuple[bool, str, int | None]:
        """Lanza la reproducción de un archivo de vídeo validado.

        Returns:
            (success, message, pid_or_none)
        """
        ...


class DefaultWindowsMediaPlayer(ManagedMediaPlayer):
    """Implementación segura por defecto del reproductor multimedia en Windows."""

    def launch(self, video_path: Path) -> tuple[bool, str, int | None]:
        return super().launch(video_path)


class WindowsMediaSkill(BaseSkill):
    """Skill de producción para reproducción gobernada de contenido multimedia en Windows."""

    def __init__(
        self,
        authorized_directory: Path | str | None = None,
        player: IMediaPlayer | None = None,
        state_path: Path | None = None,
    ) -> None:
        if authorized_directory is not None:
            self._authorized_directory = Path(authorized_directory)
        else:
            try:
                self._authorized_directory = AppSettings().JESSYCA_DANCE_VIDEO_DIRECTORY
            except Exception:
                self._authorized_directory = DEFAULT_AUTHORIZED_DANCE_DIRECTORY

        self._player: IMediaPlayer = player or DefaultWindowsMediaPlayer()
        self._last_played_video: Path | None = None
        self._execution_lock = threading.RLock()
        self._state_path = state_path
        if state_path is None and authorized_directory is None and player is None:
            self._state_path = Path(__file__).resolve().parents[1] / "data" / "media_playback_state.json"
        if self._state_path and self._state_path.is_file():
            try:
                saved = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._last_played_video = Path(saved["last_played_video"])
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("No se pudo leer el estado de reproducción; se conserva el archivo existente.")

        manifest = SkillManifest(
            id="windows.media",
            name="Windows Media Player",
            version="1.0.0",
            description="Reproduce archivos de vídeo y contenido multimedia autorizado de forma segura.",
            author="Jessyca Core",
            capabilities=("media_playback", "video_playback", "system"),
            required_tools=("media.play_random_video", "media.play_video"),
            required_agents=("DesktopAgent", "SystemAgent"),
            required_models=(),
            permissions=("media.play_random_video", "media.play_video"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.media",
            name="Windows Media Player",
            version="1.0.0",
            description="Reproducción gobernada de medios en Windows.",
            capabilities=("media_playback", "video_playback", "system"),
            required_tools=("media.play_random_video", "media.play_video"),
            required_permissions=("media.play_random_video", "media.play_video"),
            risk_level=SecurityLevel.SAFE,
            tags=("media", "video", "baile", "bailame", "reproducir", "player", "musica"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.media", nivel_riesgo=1, definition=def_obj)

    @property
    def authorized_directory(self) -> Path:
        return self._authorized_directory

    @property
    def last_played_video(self) -> Path | None:
        return self._last_played_video

    def set_last_played_video(self, video_path: Path | None) -> None:
        self._last_played_video = video_path

    def _discover_valid_videos(self, target_dir: Path, media_type: str = "video") -> list[Path]:
        """Descubre y filtra deterministamente archivos de vídeo elegibles."""
        if not target_dir.exists() or not target_dir.is_dir():
            return []

        authorized_resolved = target_dir.resolve()
        valid_videos: list[Path] = []

        try:
            for entry in target_dir.iterdir():
                # Filtrar solo archivos regulares (no carpetas ni symlinks rotos)
                if not entry.is_file():
                    continue

                # Ignorar archivos ocultos
                if entry.name.startswith("."):
                    continue

                # Filtrar estrictamente por extensiones de vídeo permitidas (case-insensitive)
                suffix_lower = entry.suffix.lower()
                extensions = SUPPORTED_AUDIO_EXTENSIONS if media_type == "audio" else SUPPORTED_VIDEO_EXTENSIONS
                if suffix_lower not in extensions:
                    continue

                # Verificar que no sea un ejecutable peligroso
                if suffix_lower in DANGEROUS_EXTENSIONS:
                    continue

                # Protección Path Traversal / Canonicalización
                entry_resolved = entry.resolve()
                try:
                    if not entry_resolved.is_relative_to(authorized_resolved):
                        logger.warning(f"[SECURITY DENY] Archivo fuera de la carpeta autorizada omitido: '{entry}'")
                        continue
                except AttributeError:
                    # Python < 3.9 fallback
                    try:
                        entry_resolved.relative_to(authorized_resolved)
                    except ValueError:
                        continue

                valid_videos.append(entry)
        except Exception as e:
            logger.error(f"[MEDIA_DISCOVERY_ERROR] Error listando directorio '{target_dir}': {e}")
            return []

        # Orden determinista para reproducibilidad
        valid_videos.sort(key=lambda p: p.name.lower())
        return valid_videos

    def _select_random_video(self, videos: list[Path]) -> Path | None:
        """Selecciona exactamente 1 vídeo aleatoriamente evitando repetición inmediata si hay >1."""
        if not videos:
            return None

        if len(videos) == 1:
            return videos[0]

        # Si hay más de 1 vídeo, evitar el último reproducido
        candidates = [v for v in videos if self._last_played_video is None or v != self._last_played_video]
        if not candidates:
            candidates = videos

        return random.choice(candidates)

    def _is_path_safe_and_authorized(self, path_to_check: Path, authorized_dir: Path) -> bool:
        """Verifica deterministamente que una ruta no intente Path Traversal y esté autorizada."""
        try:
            auth_resolved = authorized_dir.resolve()
            target_resolved = path_to_check.resolve()

            if target_resolved.suffix.lower() in DANGEROUS_EXTENSIONS:
                return False

            if target_resolved.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS:
                return False

            try:
                return target_resolved.is_relative_to(auth_resolved)
            except AttributeError:
                target_resolved.relative_to(auth_resolved)
                return True
        except Exception:
            return False

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        with self._execution_lock:
            return self._execute_serialized(parametros)

    def _execute_serialized(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta la operación de reproducción multimedia solicitada."""
        accion = str(parametros.get("accion") or parametros.get("action") or "play_random_video").lower().strip()
        req_id = str(parametros.get("request_id") or "req_media")
        exec_id = str(parametros.get("execution_id") or "exec_media")

        logger.info(f"[MEDIA_EXECUTION_REQUEST] request_id={req_id} exec_id={exec_id} action={accion}")

        # ── CASO: VALIDACIÓN DE ACCESO FUERA DE CARPETA AUTORIZADA ──
        custom_file = parametros.get("file_path") or parametros.get("ruta") or parametros.get("path")
        if custom_file:
            custom_path = Path(str(custom_file))
            requested_root = Path(str(parametros.get("target_dir") or parametros.get("directorio") or parametros.get("folder") or self._authorized_directory))
            if not self._is_path_safe_and_authorized(custom_path, requested_root):
                logger.warning(f"[SECURITY DENIED] Intento de acceso a archivo/ruta no autorizada: '{custom_file}'")
                return {
                    "exito": False,
                    "status": "DENIED",
                    "mensaje": "Acceso denegado: Ruta o tipo de archivo no autorizado.",
                    "error_code": "DENIED",
                    "execution_count": 0,
                }

        # ── CASO: DIRECTO O ALEATORIO ("play_random_video", "bailame", "play") ──
        if accion in ("play_random_video", "bailame", "play_dance", "reproducir_baile", "play_video", "play", "play_local_media", "play_local_video", "play_local_music"):
            custom_dir_param = parametros.get("target_dir") or parametros.get("directorio") or parametros.get("folder")
            if custom_dir_param:
                auth_dir = Path(str(custom_dir_param))
            else:
                auth_dir = self._authorized_directory

            # 1. Verificar si el directorio existe
            if not auth_dir.exists() or not auth_dir.is_dir():
                logger.warning(f"[DIRECTORY_NOT_FOUND] El directorio de vídeos '{auth_dir}' no existe.")
                return {
                    "exito": False,
                    "status": "DIRECTORY_NOT_FOUND",
                    "mensaje": "No encuentro la carpeta de vídeos de baile configurada.",
                    "directorio": str(auth_dir),
                    "error_code": "DIRECTORY_NOT_FOUND",
                    "execution_count": 0,
                }

            # 2. Descubrir vídeos válidos
            media_type = "audio" if accion == "play_local_music" or parametros.get("media_type") == "audio" else "video"
            if custom_file:
                requested_file = Path(str(custom_file))
                if not requested_file.is_file():
                    return {"exito": False, "status": "FILE_NOT_FOUND", "error_code": "FILE_NOT_FOUND",
                            "mensaje": "No encuentro el archivo solicitado.", "execution_count": 0}
                valid_videos = [requested_file]
            else:
                valid_videos = self._discover_valid_videos(auth_dir, media_type)
            if not valid_videos:
                logger.info(f"[NO_VIDEOS_FOUND] No se encontraron vídeos compatibles en '{auth_dir}'.")
                return {
                    "exito": False,
                    "status": "NO_VIDEOS_FOUND",
                    "mensaje": "No encontré vídeos de baile en esa carpeta.",
                    "directorio": str(auth_dir),
                    "error_code": "NO_VIDEOS_FOUND",
                    "execution_count": 0,
                }

            # 3. Seleccionar 1 vídeo aleatoriamente (evitando repetición inmediata si >1)
            selected_video = Path(str(custom_file)) if custom_file else self._select_random_video(valid_videos)
            if custom_file and not selected_video.is_file():
                return {
                    "exito": False,
                    "status": "FILE_NOT_FOUND",
                    "mensaje": "No encuentro el vídeo solicitado.",
                    "error_code": "FILE_NOT_FOUND",
                    "execution_count": 0,
                }
            if selected_video is None:
                return {
                    "exito": False,
                    "status": "NO_VIDEOS_FOUND",
                    "mensaje": "No encontré vídeos de baile en esa carpeta.",
                    "error_code": "NO_VIDEOS_FOUND",
                    "execution_count": 0,
                }

            # 4. Lanzar la reproducción EXACTAMENTE 1 VEZ mediante MediaPlayer
            logger.info(f"[MEDIA_LAUNCHING] execution_id={exec_id} video='{selected_video.name}'")
            try:
                success, launch_msg, pid = self._player.launch(selected_video)
            except Exception as exc:
                success, launch_msg, pid = False, str(exc), None

            if not success:
                logger.error(f"[MEDIA_LAUNCH_FAILED] execution_id={exec_id} error='{launch_msg}'")
                return {
                    "exito": False,
                    "status": "PLAYBACK_FAILED",
                    "mensaje": "Encontré el vídeo, pero no pude iniciar su reproducción.",
                    "video_nombre": selected_video.name,
                    "error_code": "PLAYBACK_FAILED",
                    "launch_error": launch_msg,
                    "execution_count": 0,
                }

            # Actualizar estado de último vídeo reproducido
            self._last_played_video = selected_video
            if self._state_path:
                try:
                    self._state_path.parent.mkdir(parents=True, exist_ok=True)
                    state_tmp = self._state_path.with_suffix(".tmp")
                    state_tmp.write_text(json.dumps({"last_played_video": str(selected_video.resolve())}), encoding="utf-8")
                    state_tmp.replace(self._state_path)
                except OSError as exc:
                    logger.warning(f"No se pudo guardar el último vídeo: {exc}")

            # 5. Verificación de ejecución
            try:
                evidence = get_execution_verifier().verify_execution(
                    action="play_media",
                    target=selected_video.name,
                    parameters={
                        "video_path": str(selected_video),
                        "video_name": selected_video.name,
                        "pid": pid,
                        "playback_log": str(self._player.playback_log) if getattr(self._player, "playback_log", None) else None,
                    },
                    timeout_seconds=4.0,
                )
            except Exception as exc:
                evidence = ExecutionEvidence(
                    verification_type="playback_probe_error",
                    target=selected_video.name,
                    is_verified=False,
                    details={"error": str(exc)},
                )

            if not evidence.is_verified:
                return {
                    "exito": False,
                    "status": "PLAYBACK_UNVERIFIED",
                    "mensaje": "Envié el vídeo al reproductor, pero no pude confirmar la reproducción.",
                    "respuesta_hablada": "Envié el vídeo al reproductor, pero no pude confirmar la reproducción.",
                    "video_nombre": selected_video.name,
                    "error_code": "PLAYBACK_UNVERIFIED",
                    "execution_count": 1,
                    "evidence": evidence.to_dict(),
                    "player_pid": pid,
                }

            playback_state = "PLAYBACK_LAUNCHED"
            logger.info(f"[MEDIA_PLAYBACK_SUCCESS] execution_id={exec_id} video='{selected_video.name}' state={playback_state}")

            return {
                "exito": True,
                "status": playback_state,
                "mensaje": f"Reproduciendo: {selected_video.name}",
                "respuesta_hablada": "Listo, ya está reproduciéndose.",
                "video_nombre": selected_video.name,
                "execution_count": 1,
                "evidence": evidence.to_dict(),
                "player_pid": pid,
            }

        return {
            "exito": False,
            "status": "INVALID_ACTION",
            "mensaje": f"Acción multimedia '{accion}' no reconocida.",
            "error_code": "INVALID_ACTION",
            "execution_count": 0,
        }
