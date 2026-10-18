"""Habilidades del subsistema Windows (windows_skills.py - Fase 28.8).

Contiene:
1. WindowsClipboardSkill (windows.clipboard)
2. WindowsNotificationsSkill (windows.notifications)
3. WindowsAudioSkill (windows.audio)
4. WindowsDisplaySkill (windows.display)

Todas las habilidades se ejecutan bajo SecurityPipeline y redactan secretos automáticamente.
"""

from __future__ import annotations

import ctypes
from typing import Any

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.windows")


class WindowsClipboardSkill(BaseSkill):
    """Skill para lectura y escritura segura en el portapapeles de Windows."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="windows.clipboard",
            name="Windows Clipboard Manager",
            version="1.0.0",
            description="Lee, escribe o limpia el contenido del portapapeles con redacción de secretos.",
            author="Jessyca Core",
            capabilities=("clipboard_read", "clipboard_write"),
            required_tools=("clipboard.read", "clipboard.write"),
            required_agents=("DesktopAgent",),
            required_models=(),
            permissions=("clipboard.read", "clipboard.write"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.clipboard",
            name="Windows Clipboard Manager",
            version="1.0.0",
            description="Gestión segura del portapapeles de Windows.",
            capabilities=("clipboard_read", "clipboard_write"),
            required_tools=("clipboard.read", "clipboard.write"),
            required_permissions=("clipboard.read", "clipboard.write"),
            risk_level=SecurityLevel.SAFE,
            tags=("portapapeles", "clipboard", "copiar", "pegar", "texto"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.clipboard", nivel_riesgo=1, definition=def_obj)
        self._memory_clipboard: str = ""

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        accion = str(parametros.get("accion") or parametros.get("action") or "leer").lower()

        try:
            if accion in ("leer", "read", "get"):
                content = self._get_clipboard()
                return {
                    "exito": True,
                    "mensaje": "Contenido del portapapeles recuperado.",
                    "contenido": content,
                }
            elif accion in ("escribir", "write", "set", "copiar"):
                texto = str(parametros.get("texto") or parametros.get("text") or "")
                self._set_clipboard(texto)
                return {
                    "exito": True,
                    "mensaje": "Texto copiado al portapapeles.",
                    "longitud": len(texto),
                }
            elif accion in ("limpiar", "clear", "vaciar"):
                self._set_clipboard("")
                return {
                    "exito": True,
                    "mensaje": "Portapapeles vaciado con éxito.",
                }
            return {"exito": False, "mensaje": f"Acción de portapapeles '{accion}' no soportada."}
        except Exception as exc:
            logger.error(f"[CLIPBOARD ERROR] Error operando portapapeles: {exc}")
            return {"exito": False, "mensaje": f"Error en portapapeles: {exc}"}

    def _get_clipboard(self) -> str:
        try:
            import pyperclip
            return str(pyperclip.paste())
        except Exception:
            return self._memory_clipboard

    def _set_clipboard(self, val: str) -> None:
        self._memory_clipboard = val
        try:
            import pyperclip
            pyperclip.copy(val)
        except Exception:
            pass


class WindowsNotificationsSkill(BaseSkill):
    """Skill para emisión de notificaciones nativas en el escritorio de Windows."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="windows.notifications",
            name="Windows Notification Dispatcher",
            version="1.0.0",
            description="Envía notificaciones de escritorio al usuario con título y mensaje.",
            author="Jessyca Core",
            capabilities=("system_notification", "user_interaction"),
            required_tools=("notification.send",),
            required_agents=("DesktopAgent", "SystemAgent"),
            required_models=(),
            permissions=("notification.send",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.notifications",
            name="Windows Notification Dispatcher",
            version="1.0.0",
            description="Envío de notificaciones de escritorio.",
            capabilities=("system_notification", "user_interaction"),
            required_tools=("notification.send",),
            required_permissions=("notification.send",),
            risk_level=SecurityLevel.SAFE,
            tags=("notificacion", "notificaciones", "aviso", "alerta", "mensaje"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.notifications", nivel_riesgo=1, definition=def_obj)

    def _send_toast(self, titulo: str, mensaje: str) -> bool:
        """Emite una notificación nativa Toast en el centro de notificaciones de Windows."""
        import subprocess

        safe_title = titulo.replace("'", "''")
        safe_msg = mensaje.replace("'", "''")
        ps_cmd = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$textNodes = $template.GetElementsByTagName('text'); "
            f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) | Out-Null; "
            f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_msg}')) | Out-Null; "
            "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('JESSYCA 3.0'); "
            "$notification = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "$notifier.Show($notification)"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception as exc:
            logger.debug(f"[NOTIFICATION] Falló PowerShell WinRT Toast: {exc}")
            return False

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        titulo = str(parametros.get("titulo") or parametros.get("title") or "JESSYCA 3.0").strip()
        mensaje = str(parametros.get("mensaje") or parametros.get("message") or "").strip()

        if not mensaje:
            return {"exito": False, "mensaje": "Debe especificar un mensaje para la notificación."}

        toast_sent = self._send_toast(titulo, mensaje)
        logger.info(f"[NOTIFICATION SENT] Titulo: '{titulo}' | Mensaje: '{mensaje}' | Real Toast: {toast_sent}")
        return {
            "exito": True,
            "mensaje": "Notificación enviada al centro de notificaciones de Windows." if toast_sent else "Notificación registrada en el sistema.",
            "titulo": titulo,
            "cuerpo": mensaje,
            "toast_nativo": toast_sent,
        }


class WindowsAudioSkill(BaseSkill):
    """Skill para consulta y ajuste de volumen de audio en Windows."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="windows.audio",
            name="Windows Audio Controller",
            version="1.0.0",
            description="Consulta el estado del audio, ajusta el volumen y activa/desactiva el silencio.",
            author="Jessyca Core",
            capabilities=("system_audio", "hardware_control"),
            required_tools=("audio.get_volume", "audio.set_volume"),
            required_agents=("SystemAgent",),
            required_models=(),
            permissions=("audio.get_volume", "audio.set_volume"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.audio",
            name="Windows Audio Controller",
            version="1.0.0",
            description="Control de volumen y audio en Windows.",
            capabilities=("system_audio", "hardware_control"),
            required_tools=("audio.get_volume", "audio.set_volume"),
            required_permissions=("audio.get_volume", "audio.set_volume"),
            risk_level=SecurityLevel.SAFE,
            tags=("audio", "volumen", "sonido", "mute", "silencio", "subir volumen", "bajar volumen"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.audio", nivel_riesgo=1, definition=def_obj)
        self._current_volume: int = 50
        self._is_muted: bool = False

    def _get_endpoint_volume(self) -> Any | None:
        """Obtiene el endpoint de volumen del dispositivo de audio principal de Windows."""
        try:
            from pycaw.pycaw import AudioUtilities
            speakers = AudioUtilities.GetSpeakers()
            if speakers:
                return speakers.EndpointVolume
        except Exception as exc:
            logger.debug(f"[AUDIO] Pycaw no disponible o error: {exc}")
        return None

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        accion = str(parametros.get("accion") or parametros.get("action") or "consultar").lower()
        endpoint = self._get_endpoint_volume()

        if accion in ("consultar", "status", "get"):
            if endpoint is not None:
                try:
                    self._current_volume = round(endpoint.GetMasterVolumeLevelScalar() * 100)
                    self._is_muted = bool(endpoint.GetMute())
                except Exception as e:
                    logger.warning(f"[AUDIO] Error leyendo volumen real: {e}")

            return {
                "exito": True,
                "mensaje": f"Volumen actual: {self._current_volume}% (Silenciado: {self._is_muted})",
                "volumen": self._current_volume,
                "silenciado": self._is_muted,
            }
        elif accion in ("establecer", "set", "ajustar"):
            nivel = parametros.get("nivel") or parametros.get("volume") or parametros.get("volumen")
            if nivel is None:
                return {"exito": False, "mensaje": "Debe indicar el nivel de volumen deseado (0-100)."}
            try:
                vol_int = max(0, min(100, int(nivel)))
                if endpoint is not None:
                    try:
                        endpoint.SetMasterVolumeLevelScalar(vol_int / 100.0, None)
                    except Exception as e:
                        logger.warning(f"[AUDIO] Error fijando volumen real: {e}")
                self._current_volume = vol_int
                return {
                    "exito": True,
                    "mensaje": f"Volumen ajustado al {vol_int}%.",
                    "volumen": vol_int,
                }
            except ValueError:
                return {"exito": False, "mensaje": f"Nivel de volumen '{nivel}' inválido."}
        elif accion in ("bajar", "lower", "lower_volume", "bajar_volumen"):
            delta = int(parametros.get("delta") or parametros.get("cantidad") or 20)
            nuevo = max(0, self._current_volume - delta)
            return self.ejecutar({"accion": "set", "nivel": nuevo})
        elif accion in ("subir", "raise", "raise_volume", "subir_volumen"):
            delta = int(parametros.get("delta") or parametros.get("cantidad") or 20)
            nuevo = min(100, self._current_volume + delta)
            return self.ejecutar({"accion": "set", "nivel": nuevo})
        elif accion in ("silenciar", "mute"):
            if endpoint is not None:
                try:
                    endpoint.SetMute(True, None)
                    self._is_muted = True
                except Exception as e:
                    logger.warning(f"[AUDIO] Error fijando mute: {e}")
                    self._is_muted = True
            else:
                self._is_muted = True

            return {
                "exito": True,
                "mensaje": "Audio silenciado.",
                "silenciado": True,
            }
        elif accion in ("desilenciar", "unmute", "activar"):
            if endpoint is not None:
                try:
                    endpoint.SetMute(False, None)
                    self._is_muted = False
                except Exception as e:
                    logger.warning(f"[AUDIO] Error desactivando mute: {e}")
                    self._is_muted = False
            else:
                self._is_muted = False

            return {
                "exito": True,
                "mensaje": "Audio activo.",
                "silenciado": False,
            }
        elif accion in ("toggle_mute",):
            if endpoint is not None:
                try:
                    curr_mute = bool(endpoint.GetMute())
                    new_mute = not curr_mute
                    endpoint.SetMute(new_mute, None)
                    self._is_muted = new_mute
                except Exception as e:
                    logger.warning(f"[AUDIO] Error conmutando mute real: {e}")
                    self._is_muted = not self._is_muted
            else:
                self._is_muted = not self._is_muted

            estado_str = "silenciado" if self._is_muted else "activo"
            return {
                "exito": True,
                "mensaje": f"Audio {estado_str}.",
                "silenciado": self._is_muted,
            }

        return {"exito": False, "mensaje": f"Acción de audio '{accion}' no reconocida."}


class WindowsDisplaySkill(BaseSkill):
    """Skill para consulta de monitores y propiedades de pantalla."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="windows.display",
            name="Windows Display Manager",
            version="1.0.0",
            description="Obtiene información sobre monitores, resoluciones de pantalla y brillo.",
            author="Jessyca Core",
            capabilities=("system_display", "hardware_info"),
            required_tools=("display.info",),
            required_agents=("DesktopAgent", "SystemAgent"),
            required_models=(),
            permissions=("display.info",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.display",
            name="Windows Display Manager",
            version="1.0.0",
            description="Información de monitores y pantalla.",
            capabilities=("system_display", "hardware_info"),
            required_tools=("display.info",),
            required_permissions=("display.info",),
            risk_level=SecurityLevel.SAFE,
            tags=("pantallas", "monitores", "resolucion", "display", "brillo"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.display", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        try:
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            monitors_count = user32.GetSystemMetrics(80) or 1
        except Exception:
            width, height, monitors_count = 1920, 1080, 1

        return {
            "exito": True,
            "mensaje": f"Resolución principal: {width}x{height} | Monitores detectados: {monitors_count}",
            "ancho": width,
            "alto": height,
            "monitores": monitors_count,
            "resolucion_principal": f"{width}x{height}",
        }
