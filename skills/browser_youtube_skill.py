"""Skill de navegación, búsqueda y reproducción en YouTube (browser_youtube_skill.py - Fase 75.1).

Implementa la capacidad oficial 'browser.youtube' gobernada para JESSYCA:
    1. "Abre YouTube" -> open
    2. "Busca <canción> en YouTube" -> search
    3. "Reproduce <canción> en YouTube" / "Abre YouTube y reproduce <canción>" -> play (tarea compuesta)

Flujo de la Tarea Compuesta:
    OPEN_YOUTUBE -> SEARCH_YOUTUBE -> SELECT_RESULT -> PLAY_MEDIA -> VERIFY_PLAYBACK

GARANTÍA DE ANTI-FALSO ÉXITO:
    Si la búsqueda o la reproducción fallan, NO se afirma éxito.
    La respuesta se deriva estrictamente del resultado observable de la ejecución y verificación.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from core.browser_session_manager import BrowserSessionManager
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.browser_youtube")


class BrowserYouTubeSkill(BaseSkill):
    """Skill oficial de producción para control, búsqueda y reproducción en YouTube."""

    def __init__(
        self,
        session_manager: BrowserSessionManager | None = None,
        video_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._custom_resolver = video_resolver

        manifest = SkillManifest(
            id="browser.youtube",
            name="YouTube Media Player",
            version="1.0.0",
            description="Controla la navegación, búsqueda y reproducción de contenido en YouTube mediante Microsoft Edge.",
            author="Jessyca Core",
            capabilities=("browser_navigation", "media_playback", "web_search"),
            required_tools=("browser.open", "browser.navigate", "browser.media"),
            required_agents=("BrowserAgent",),
            required_models=("llama3.2:latest",),
            permissions=("browser.open", "browser.navigate", "browser.media"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="browser.youtube",
            name="YouTube Media Player",
            version="1.0.0",
            description="Apertura, búsqueda y reproducción gobernada en YouTube.",
            capabilities=("browser_navigation", "media_playback", "web_search"),
            required_tools=("browser.open", "browser.navigate", "browser.media"),
            required_permissions=("browser.open", "browser.navigate", "browser.media"),
            risk_level=SecurityLevel.SAFE,
            tags=("youtube", "musica", "video", "reproducir", "cancion", "media", "browser"),
            manifest=manifest,
        )
        super().__init__(nombre="browser.youtube", nivel_riesgo=1, definition=def_obj)

    def _get_session_manager(self) -> BrowserSessionManager:
        if self._session_manager is None:
            self._session_manager = BrowserSessionManager()
        return self._session_manager

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Punto de entrada de la Skill para operaciones de YouTube."""
        operacion = str(parametros.get("operacion") or parametros.get("action") or parametros.get("operation") or "").strip().lower()
        query = str(
            parametros.get("query")
            or parametros.get("cancion")
            or parametros.get("termino")
            or parametros.get("video")
            or ""
        ).strip()

        # Determinar operación implícita si no viene explícita
        if not operacion:
            if query and ("reproduce" in query.lower() or parametros.get("action") == "play"):
                operacion = "play"
            elif query:
                operacion = "search"
            else:
                operacion = "open"

        if operacion in ("open", "abrir", "open_youtube"):
            return self._execute_open()
        elif operacion in ("search", "buscar", "search_youtube"):
            return self._execute_search(query)
        elif operacion in ("play", "reproducir", "play_media", "compound_open_and_play", "search_and_play"):
            return self._execute_compound_play(query, parametros)
        else:
            return {
                "exito": False,
                "error_code": "UNKNOWN_OPERATION",
                "mensaje": f"Operación '{operacion}' no soportada por browser.youtube.",
                "step": "INIT",
                "verified": False,
            }

    def _execute_open(self) -> dict[str, Any]:
        """Abre la página principal de YouTube en el navegador."""
        url = "https://www.youtube.com"
        bsm = self._get_session_manager()
        try:
            tab = bsm.open_url(url)
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

            return {
                "exito": True,
                "executed": True,
                "step": "OPEN_YOUTUBE",
                "steps_executed": ("OPEN_YOUTUBE",),
                "url": url,
                "tab_id": tab.tab_id if tab else "tab-1",
                "mensaje": "Se solicitó abrir YouTube en el navegador.",
                "verified": False,
                "verification_status": "UNVERIFIED",
                "verification_required": True,
            }
        except Exception as exc:
            logger.error(f"[YOUTUBE OPEN ERROR] Fallo al abrir YouTube: {exc}")
            return {
                "exito": False,
                "step": "OPEN_YOUTUBE",
                "error_code": "OPEN_FAILED",
                "mensaje": f"No pude abrir YouTube en el navegador: {exc}",
                "verified": False,
                "verification_status": "FAILED",
            }

    def _execute_search(self, query: str) -> dict[str, Any]:
        """Realiza una búsqueda directa en YouTube."""
        clean_query = self._clean_query_text(query)
        if not clean_query:
            return {
                "exito": False,
                "step": "SEARCH_YOUTUBE",
                "error_code": "EMPTY_QUERY",
                "mensaje": "Debe especificar un término para buscar en YouTube.",
                "verified": False,
                "verification_status": "FAILED",
            }

        encoded = urllib.parse.quote(clean_query)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"
        bsm = self._get_session_manager()

        try:
            tab = bsm.open_url(search_url)
            try:
                import webbrowser
                webbrowser.open(search_url)
            except Exception:
                pass

            # Intentar resolver el video ID relevante para enriquecer el resultado
            video_id = self.resolve_video_id(clean_query)

            return {
                "exito": True,
                "executed": True,
                "step": "SEARCH_YOUTUBE",
                "steps_executed": ("OPEN_YOUTUBE", "SEARCH_YOUTUBE"),
                "query": clean_query,
                "url": search_url,
                "video_id": video_id,
                "tab_id": tab.tab_id if tab else "tab-1",
                "mensaje": f"Se envió la búsqueda de '{clean_query}' a YouTube.",
                "verified": False,
                "verification_status": "UNVERIFIED",
                "verification_required": True,
            }
        except Exception as exc:
            logger.error(f"[YOUTUBE SEARCH ERROR] Fallo en búsqueda YouTube: {exc}")
            return {
                "exito": False,
                "step": "SEARCH_YOUTUBE",
                "error_code": "SEARCH_FAILED",
                "query": clean_query,
                "mensaje": f"No pude realizar la búsqueda de '{clean_query}' en YouTube: {exc}",
                "verified": False,
                "verification_status": "FAILED",
            }

    def _execute_compound_play(self, query: str, parametros: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta la tarea compuesta completa:

        1. OPEN_YOUTUBE -> Abre o enfoca YouTube.
        2. SEARCH_YOUTUBE -> Busca la canción solicitada.
        3. SELECT_RESULT -> Selecciona el resultado más relevante (video_id).
        4. PLAY_MEDIA -> Abre la URL directa de reproducción (watch?v=...).
        5. VERIFY_PLAYBACK -> Verifica que el proceso esté activo y reproduciendo.
        """
        clean_query = self._clean_query_text(query)
        if not clean_query:
            return {
                "exito": False,
                "step": "SEARCH_YOUTUBE",
                "error_code": "EMPTY_QUERY",
                "mensaje": "No especificaste qué canción o vídeo reproducir.",
                "verified": False,
                "verification_status": "FAILED",
            }

        steps_done: list[str] = []
        bsm = self._get_session_manager()

        # PASO 1: OPEN_YOUTUBE
        steps_done.append("OPEN_YOUTUBE")
        logger.info(f"[YOUTUBE COMPOUND] Paso 1/5: OPEN_YOUTUBE para '{clean_query}'")

        # PASO 2 & 3: SEARCH_YOUTUBE & SELECT_RESULT
        steps_done.append("SEARCH_YOUTUBE")
        logger.info(f"[YOUTUBE COMPOUND] Paso 2/5: SEARCH_YOUTUBE con término '{clean_query}'")

        video_id: str | None = None
        # Comprobar si vino forzado por test o parámetro
        if parametros.get("simulated_search_failure"):
            logger.warning("[YOUTUBE COMPOUND] Simulación de fallo en búsqueda activada.")
            return {
                "exito": False,
                "step": "SEARCH_YOUTUBE",
                "steps_executed": tuple(steps_done),
                "error_code": "SEARCH_FAILED",
                "query": clean_query,
                "mensaje": f"No pude encontrar resultados para '{clean_query}' en YouTube.",
                "verified": False,
                "verification_status": "FAILED",
            }

        if parametros.get("video_id"):
            video_id = str(parametros["video_id"])
        else:
            video_id = self.resolve_video_id(clean_query)

        if not video_id:
            logger.warning(f"[YOUTUBE COMPOUND] No se encontró ningún vídeo para '{clean_query}'.")
            return {
                "exito": False,
                "step": "SELECT_RESULT",
                "steps_executed": tuple(steps_done),
                "error_code": "SEARCH_FAILED",
                "query": clean_query,
                "mensaje": f"No pude encontrar la canción '{clean_query}' en YouTube.",
                "verified": False,
                "verification_status": "FAILED",
            }

        steps_done.append("SELECT_RESULT")
        logger.info(f"[YOUTUBE COMPOUND] Paso 3/5: SELECT_RESULT seleccionado ID={video_id}")

        # PASO 4: PLAY_MEDIA
        steps_done.append("PLAY_MEDIA")
        target_video_url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"[YOUTUBE COMPOUND] Paso 4/5: PLAY_MEDIA abriendo '{target_video_url}'")

        if parametros.get("simulated_play_failure"):
            logger.warning("[YOUTUBE COMPOUND] Simulación de fallo en reproducción activada.")
            return {
                "exito": False,
                "step": "PLAY_MEDIA",
                "steps_executed": tuple(steps_done),
                "error_code": "PLAYBACK_FAILED",
                "query": clean_query,
                "video_id": video_id,
                "url": target_video_url,
                "mensaje": f"Logré abrir YouTube, pero no pude iniciar la reproducción de '{clean_query}'.",
                "verified": False,
                "verification_status": "FAILED",
            }

        try:
            tab = bsm.open_url(target_video_url)
            try:
                import webbrowser
                webbrowser.open(target_video_url)
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"[YOUTUBE COMPOUND PLAY ERROR] Error al abrir URL de vídeo: {exc}")
            return {
                "exito": False,
                "step": "PLAY_MEDIA",
                "steps_executed": tuple(steps_done),
                "error_code": "PLAYBACK_FAILED",
                "query": clean_query,
                "video_id": video_id,
                "mensaje": f"Logré abrir YouTube, pero no pude iniciar la reproducción de '{clean_query}'.",
                "verified": False,
                "verification_status": "FAILED",
            }

        # En la Fase 1, la skill termina en PLAY_MEDIA solicitada sin auto-certificarse.
        # La verificación real de reproducción corresponde al ExecutionVerifier externo (Fase 3).
        if parametros.get("simulate_unverifiable"):
            return {
                "exito": True,
                "executed": True,
                "step": "PLAY_MEDIA",
                "steps_executed": tuple(steps_done),
                "query": clean_query,
                "video_id": video_id,
                "url": target_video_url,
                "mensaje": f"Abrí la página de YouTube para '{clean_query}', pero no fue posible verificar la reproducción.",
                "verified": False,
                "verification_status": "NOT_VERIFIABLE",
                "verification_required": True,
                "media_state": "MEDIA_UNKNOWN",
            }

        return {
            "exito": True,
            "executed": True,
            "step": "PLAY_MEDIA",
            "steps_executed": tuple(steps_done),
            "query": clean_query,
            "video_id": video_id,
            "url": target_video_url,
            "tab_id": tab.tab_id if tab else "tab-1",
            "mensaje": f"Se solicitó reproducir {clean_query} en YouTube.",
            "verified": False,
            "verification_status": "UNVERIFIED",
            "verification_required": True,
            "media_state": "MEDIA_UNKNOWN",
        }

    def resolve_video_id(self, query: str) -> str | None:
        """Resuelve el ID de vídeo (11 caracteres) para una consulta de búsqueda."""
        if self._custom_resolver:
            return self._custom_resolver(query)

        # Si la consulta ya incluye watch?v=...
        direct_match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", query)
        if direct_match:
            return direct_match.group(1)

        clean_q = self._clean_query_text(query)
        if not clean_q:
            return None

        # Intento de resolución en vivo mediante scraping seguro y ligero de resultados
        try:
            encoded = urllib.parse.quote(clean_q)
            req = urllib.request.Request(
                f"https://www.youtube.com/results?search_query={encoded}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=3.5) as response:
                html = response.read().decode("utf-8", errors="ignore")
                matches = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
                if matches:
                    selected = str(matches[0])
                    logger.info(f"[YOUTUBE RESOLVER] ID resuelto para '{clean_q}': {selected}")
                    return selected
        except Exception as exc:
            logger.debug(f"[YOUTUBE RESOLVER] Consulta en vivo no disponible ({exc}).")

        # NUNCA generar IDs sintéticos artificiales si no se encontró un video real (Fase 1)
        return None

    def _clean_query_text(self, text: str) -> str:
        """Limpia el texto de la petición retirando comandos y palabras vacías."""
        q = text.strip()
        # Retirar prefijos de órdenes
        q = re.sub(r"^(?:jessyca|jessica)[,\s]*", "", q, flags=re.IGNORECASE)
        q = re.sub(r"^(?:ahora\s*)?(?:y\s*)?(?:abre\s+youtube\s+y\s+)?(?:reproduce|pon|busca\s+y\s+reproduce|busca|buscar)\s+", "", q, flags=re.IGNORECASE)
        # Retirar calificadores
        q = re.sub(r"^(?:la\s+canción|la\s+cancion|la\s+música|la\s+musica|el\s+tema|el\s+video|el\s+vídeo)\s+", "", q, flags=re.IGNORECASE)
        # Retirar sufijos "en youtube" / "de youtube"
        q = re.sub(r"\s+(?:en|de)\s+youtube\s*$", "", q, flags=re.IGNORECASE)
        return q.strip()
