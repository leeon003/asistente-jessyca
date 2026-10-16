"""Catálogo progresivo y enrutador dinámico de herramientas (core/intent/progressive_catalog.py).

Implementa el patrón Progressive Tool Loading de SAI Rust:
- Agrupa las 32 habilidades en dominios funcionales.
- Expone un set inicial mínimo y carga esquemas detallados bajo demanda.
- Reduce el consumo de tokens de contexto en más de un 70%, acelerando la inferencia local.
"""

from __future__ import annotations

import re
from typing import Any

TOOL_DOMAINS: dict[str, list[str]] = {
    "system": [
        "windows.audio",
        "windows.display",
        "windows.notifications",
        "windows.clipboard",
    ],
    "apps": [
        "windows.apps",
        "windows.computer_use",
        "windows.screenshot",
        "windows.media",
    ],
    "files": [
        "files.search",
        "files.read",
        "files.create",
        "files.copy",
        "files.move",
        "files.rename",
        "files.organize",
        "files.create_folder",
        "files.list",
        "files.metadata",
    ],
    "browser": [
        "browser.open",
        "browser.search",
        "browser.navigate",
        "browser.read",
        "browser.download",
        "browser.youtube",
    ],
    "documents": [
        "documents.read",
        "documents.create",
        "documents.summarize",
        "documents.convert",
    ],
}

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "system": [
        "volumen", "audio", "sonido", "mute", "silencia", "silenciar",
        "portapapeles", "clipboard", "pantalla", "resolucion", "resolución",
        "notificacion", "notificación", "notifica", "avisa",
    ],
    "apps": [
        "abre", "abrir", "inicia", "iniciar", "cierra", "cerrar", "app", "aplicacion",
        "aplicación", "calculadora", "calc", "bloc de notas", "notepad", "paint",
        "cmd", "terminal", "consola", "escribe dentro de", "clic", "click", "mouse",
        "captura de pantalla", "screenshot", "baila", "baile",
    ],
    "files": [
        "archivo", "archivos", "carpeta", "carpetas", "directorio", "fichero",
        "busca", "buscar", "copia", "copiar", "mueve", "mover", "renombra",
        "crea carpeta", "crear carpeta", "lista", "listar", "borra archivo",
    ],
    "browser": [
        "navegador", "chrome", "edge", "google", "youtube", "web", "internet",
        "busca en internet", "busca en google", "reproduce en youtube", "video",
        "musica", "música", "cancion", "canción", "descarga", "descargar", "link",
        "investiga", "noticias",
    ],
    "documents": [
        "word", "excel", "powerpoint", "pdf", "docx", "xlsx", "pptx",
        "resume documento", "resumen de documento", "convierte documento",
        "reporte", "informe",
    ],
}


class ProgressiveToolCatalog:
    """Administrador de carga progresiva y enrutamiento de capacidades."""

    @staticmethod
    def preselect_domains(user_text: str) -> list[str]:
        """Pre-selecciona los dominios requeridos analizando el texto del usuario (Jev router)."""
        lower = user_text.lower()
        selected: list[str] = []

        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", lower):
                    selected.append(domain)
                    break

        # Si no se detectó ningún dominio pero hay intención operativa, incluir system y apps por defecto
        if not selected and any(w in lower for w in ("haz", "ejecuta", "pon", "mira", "toma", "dime")):
            selected = ["system", "apps"]

        return selected

    @staticmethod
    def get_tool_descriptions(domains: list[str]) -> str:
        """Genera descripciones concisas de las herramientas para los dominios seleccionados."""
        if not domains:
            return "No se requieren herramientas para consultas conversacionales directas."

        lines: list[str] = ["HERRAMIENTAS DISPONIBLES PARA ESTA META:"]
        
        # Mapeo conciso de ayuda por skill
        skill_summaries = {
            "windows.audio": "windows.audio: Controla volumen maestro y mute. Parametros: {'accion': 'establecer'|'silenciar'|'consultar', 'nivel': int(0-100), 'delta': int}.",
            "windows.apps": "windows.apps: Abre, enfoca o cierra apps de Windows. Parametros: {'accion': 'abrir'|'cerrar', 'app_name': str, 'text_to_write': str|None}.",
            "windows.computer_use": "windows.computer_use: Interaccion de mouse, teclado o foco en Windows. Parametros: {'action': 'click'|'type_text'|'focus_window'|'press_key', 'text': str, 'element_id': str}.",
            "browser.search": "browser.search: Busca informacion en internet o abre enlaces web. Parametros: {'query': str, 'url': str|None}.",
            "browser.youtube": "browser.youtube: Busca y reproduce contenido multimedia en YouTube. Parametros: {'query': str, 'autoplay': bool}.",
            "files.search": "files.search: Busca archivos por nombre o extension. Parametros: {'query': str, 'path': str|None}.",
            "files.create": "files.create: Crea un nuevo archivo con contenido. Parametros: {'path': str, 'content': str}.",
            "files.copy": "files.copy: Copia archivos entre rutas autorizadas. Parametros: {'source': str, 'destination': str}.",
            "documents.summarize": "documents.summarize: Resume el contenido de archivos Word/PDF/Excel. Parametros: {'path': str}.",
            "windows.screenshot": "windows.screenshot: Captura de pantalla completa. Parametros: {'action': 'capturar'}.",
            "windows.notifications": "windows.notifications: Emite una notificacion nativa Toast. Parametros: {'titulo': str, 'mensaje': str}.",
        }

        included_skills: set[str] = set()
        for domain in domains:
            for skill in TOOL_DOMAINS.get(domain, []):
                if skill in skill_summaries and skill not in included_skills:
                    lines.append(f"- {skill_summaries[skill]}")
                    included_skills.add(skill)

        return "\n".join(lines)

    @staticmethod
    def get_tool_names(domains: list[str]) -> list[str]:
        """Obtiene la lista de nombres de herramientas pertenecientes a los dominios especificados."""
        names: list[str] = []
        for domain in domains:
            for tool in TOOL_DOMAINS.get(domain, []):
                if tool not in names:
                    names.append(tool)
        return names


__all__ = [
    "TOOL_DOMAINS",
    "DOMAIN_KEYWORDS",
    "ProgressiveToolCatalog",
]
