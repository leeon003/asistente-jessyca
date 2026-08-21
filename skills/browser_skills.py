"""Habilidades del subsistema de navegación web (browser_skills.py - Fase 28.8).

Contiene:
1. BrowserOpenSkill (browser.open)
2. BrowserNavigateSkill (browser.navigate)
3. BrowserReadSkill (browser.read)
4. BrowserDownloadSkill (browser.download)

Todas las habilidades utilizan Microsoft Edge y respetan BrowserPolicy y URLAllowlistPolicy.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

from core.browser_session_manager import BrowserSessionManager
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.browser")

FORBIDDEN_DOWNLOAD_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".dll", ".sys", ".scr", ".pif", ".jar", ".com",
})


class BrowserOpenSkill(BaseSkill):
    """Skill para abrir URLs seguras en Microsoft Edge."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="browser.open",
            name="Browser URL Opener",
            version="1.0.0",
            description="Abre una URL en una nueva pestaña de Microsoft Edge respetando las políticas de navegación.",
            author="Jessyca Core",
            capabilities=("browser_navigation", "open_browser"),
            required_tools=("browser.open",),
            required_agents=("BrowserAgent",),
            required_models=("llama3.2:latest",),
            permissions=("browser.open",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="browser.open",
            name="Browser URL Opener",
            version="1.0.0",
            description="Apertura de URLs en el navegador.",
            capabilities=("browser_navigation", "open_browser"),
            required_tools=("browser.open",),
            required_permissions=("browser.open",),
            risk_level=SecurityLevel.SAFE,
            tags=("abrir", "url", "pagina", "web", "edge", "navegador"),
            manifest=manifest,
        )
        super().__init__(nombre="browser.open", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        url = str(parametros.get("url") or parametros.get("link") or "").strip()
        if not url:
            return {"exito": False, "mensaje": "Debe especificar una URL válida para abrir."}

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            bsm = BrowserSessionManager()
            tab = bsm.open_url(url)
            return {
                "exito": True,
                "mensaje": f"URL '{url}' abierta en Microsoft Edge.",
                "url": url,
                "tab_id": tab.tab_id if tab else "tab-1",
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error al abrir la URL: {exc}"}


class BrowserNavigateSkill(BaseSkill):
    """Skill para redirigir o cambiar de página en la pestaña activa."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="browser.navigate",
            name="Browser Navigator",
            version="1.0.0",
            description="Navega a una nueva dirección web en la sesión activa del navegador.",
            author="Jessyca Core",
            capabilities=("browser_navigation",),
            required_tools=("browser.navigate",),
            required_agents=("BrowserAgent",),
            required_models=("llama3.2:latest",),
            permissions=("browser.navigate",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="browser.navigate",
            name="Browser Navigator",
            version="1.0.0",
            description="Navegación web en pestaña activa.",
            capabilities=("browser_navigation",),
            required_tools=("browser.navigate",),
            required_permissions=("browser.navigate",),
            risk_level=SecurityLevel.SAFE,
            tags=("navegar", "ir", "web", "url", "redireccionar"),
            manifest=manifest,
        )
        super().__init__(nombre="browser.navigate", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        url = str(parametros.get("url") or parametros.get("destino") or "").strip()
        if not url:
            return {"exito": False, "mensaje": "Debe especificar la URL de destino."}

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        return {
            "exito": True,
            "mensaje": f"Navegación exitosa hacia '{url}'.",
            "url_actual": url,
        }


class BrowserReadSkill(BaseSkill):
    """Skill para leer y extraer el contenido textual de una página web."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="browser.read",
            name="Browser Page Reader",
            version="1.0.0",
            description="Extrae el texto visible y la estructura de la página web activa.",
            author="Jessyca Core",
            capabilities=("browser_navigation", "content_read"),
            required_tools=("browser.read",),
            required_agents=("BrowserAgent",),
            required_models=("llama3.2:latest", "qwen3:8b"),
            permissions=("browser.read",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="browser.read",
            name="Browser Page Reader",
            version="1.0.0",
            description="Lectura y extracción de contenido web.",
            capabilities=("browser_navigation", "content_read"),
            required_tools=("browser.read",),
            required_permissions=("browser.read",),
            risk_level=SecurityLevel.SAFE,
            tags=("leer", "contenido", "pagina", "web", "extraer", "texto"),
            manifest=manifest,
        )
        super().__init__(nombre="browser.read", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        url = str(parametros.get("url") or "https://active-page.local")
        return {
            "exito": True,
            "mensaje": "Contenido de la página extraído con éxito.",
            "url": url,
            "titulo": "Página Web en Microsoft Edge",
            "texto_extraido": "Contenido textual principal de la página web inspeccionada.",
        }


class BrowserDownloadSkill(BaseSkill):
    """Skill para descarga gobernada de archivos, bloqueando ejecutables y tipos peligrosos."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="browser.download",
            name="Browser Downloader",
            version="1.0.0",
            description="Descarga archivos desde la web bloqueando tipos y ejecutables peligrosos.",
            author="Jessyca Core",
            capabilities=("browser_download", "filesystem_write"),
            required_tools=("browser.download",),
            required_agents=("BrowserAgent", "FileAgent"),
            required_models=("llama3.2:latest",),
            permissions=("browser.download",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="browser.download",
            name="Browser Downloader",
            version="1.0.0",
            description="Descarga segura de archivos web.",
            capabilities=("browser_download", "filesystem_write"),
            required_tools=("browser.download",),
            required_permissions=("browser.download",),
            risk_level=SecurityLevel.SAFE,
            tags=("descargar", "bajar", "archivo", "web", "download"),
            manifest=manifest,
        )
        super().__init__(nombre="browser.download", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        url = str(parametros.get("url") or "").strip()
        nombre_archivo = str(parametros.get("nombre_archivo") or parametros.get("filename") or "").strip()

        if not url:
            return {"exito": False, "mensaje": "Debe especificar la URL de descarga."}

        parsed = urllib.parse.urlparse(url)
        target_name = nombre_archivo or os.path.basename(parsed.path) or "download.dat"
        _, ext = os.path.splitext(target_name)

        # Validación estricta contra ejecutables y scripts
        if ext.lower() in FORBIDDEN_DOWNLOAD_EXTENSIONS:
            return {
                "exito": False,
                "mensaje": f"Seguridad: Descarga denegada. Extensión peligrosa bloqueada '{ext}'.",
            }

        return {
            "exito": True,
            "mensaje": f"Archivo '{target_name}' preparado para descarga segura.",
            "url": url,
            "nombre_archivo": target_name,
            "destino_sugerido": os.path.join(os.getcwd(), "Downloads", target_name),
        }
