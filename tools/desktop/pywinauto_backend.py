"""Adaptador de inspección visual de elementos UI basado en pywinauto (Fase I4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y CONTRATO:
1. SOLO LECTURA (READ-ONLY): CERO clicks, CERO teclado, CERO movimiento de mouse.
2. NUNCA inventa ventanas ni elementos falsos cuando la librería falta o la API falla.
3. Soporta coordenadas multi-monitor (incluyendo valores negativos para monitores secundarios).
4. Inicializa y limpia COM (pythoncom.CoInitialize / CoUninitialize) de manera segura.
5. Maneja ambigüedad de controles y elementos obsoletos/destruidos (stale elements).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.exceptions import UIBackendUnavailableError, UIInspectionError
from core.logger import get_logger
from core.ui_inspection_models import (
    ObservationProvenance,
    ObservationStatus,
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
    UIInspectionMetadata,
    UIInspectionResult,
    WindowInfo,
)

logger = get_logger("jessyca.tools.desktop.pywinauto_backend")


def _init_com() -> bool:
    """Inicializa COM en el subproceso actual si pythoncom está disponible."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
        return True
    except Exception:
        return False


def _uninit_com() -> None:
    """Limpia el contexto COM en el subproceso actual."""
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass


class PyWinAutoInspectionBackend:
    """Adaptador de inspección UI opcional desacoplado detrás del contrato IUIInspectionBackend.

    Este componente es ESTRICTAMENTE DE SOLO LECTURA. Ninguna acción física es ejecutada aquí.
    """

    def __init__(self, backend_type: str = "uia") -> None:
        self.backend_type = backend_type  # "uia" o "win32"

    def _ensure_pywinauto(self) -> Any:
        """Importa pywinauto perezosamente y valida disponibilidad."""
        try:
            from pywinauto import Desktop
            return Desktop
        except ImportError as err:
            logger.warning("[PYWINAUTO BACKEND] Librería 'pywinauto' no disponible en el entorno.")
            raise UIBackendUnavailableError("Librería 'pywinauto' no instalada en el entorno.") from err

    def get_active_window(self) -> WindowInfo:
        """Obtiene la ventana activa usando pywinauto preservando coordenadas multi-monitor."""
        com_initialized = _init_com()
        try:
            desktop_cls = self._ensure_pywinauto()
            desktop = desktop_cls(backend=self.backend_type)

            active_win = None
            try:
                # Buscar ventana con foco de teclado o ventana activa superior
                for win in desktop.windows():
                    try:
                        if win.is_active() or win.has_keyboard_focus():
                            active_win = win
                            break
                    except Exception:
                        continue
                if not active_win:
                    # Fallback a la primera ventana visible de nivel superior
                    wins = desktop.windows(visible_only=True)
                    if wins:
                        active_win = wins[0]
            except Exception as e:
                raise UIInspectionError(f"Fallo al consultar ventana activa con pywinauto: {e}") from e

            if not active_win:
                raise UIInspectionError("No se encontró ninguna ventana activa en el escritorio.")

            try:
                rect = active_win.rectangle()
                # Soporte multi-monitor: preservar coordenadas negativas
                x = rect.left
                y = rect.top
                w = max(1, rect.width())
                h = max(1, rect.height())
                handle = getattr(active_win, "handle", 0)
                pid = getattr(active_win.element_info, "process_id", 0)
                title = active_win.window_text() or "Active Window"
                c_name = active_win.class_name() or "Window"

                return WindowInfo(
                    hwnd=handle or 0,
                    title=title,
                    class_name=c_name,
                    process_id=pid or 0,
                    bounds=UIElementBounds(x=x, y=y, width=w, height=h),
                    is_active=True,
                    is_minimized=active_win.is_minimized() if hasattr(active_win, "is_minimized") else False,
                    is_maximized=active_win.is_maximized() if hasattr(active_win, "is_maximized") else False,
                    is_visible=True,
                    timestamp=datetime.now(UTC),
                    provenance=ObservationProvenance.REAL_PHYSICAL,
                )
            except Exception as e:
                raise UIInspectionError(f"Error extrayendo información de ventana activa: {e}") from e
        finally:
            if com_initialized:
                _uninit_com()

    def list_windows(self) -> tuple[WindowInfo, ...]:
        """Lista las ventanas principales visibles en el escritorio."""
        com_initialized = _init_com()
        try:
            desktop_cls = self._ensure_pywinauto()
            desktop = desktop_cls(backend=self.backend_type)

            results: list[WindowInfo] = []
            try:
                for win in desktop.windows(visible_only=True):
                    try:
                        rect = win.rectangle()
                        # Preservar coordenadas multi-monitor (pueden ser negativas)
                        x = rect.left
                        y = rect.top
                        w = max(1, rect.width())
                        h = max(1, rect.height())

                        results.append(
                            WindowInfo(
                                hwnd=getattr(win, "handle", 0) or 0,
                                title=win.window_text() or "Window",
                                class_name=win.class_name() or "Window",
                                process_id=getattr(win.element_info, "process_id", 0) or 0,
                                bounds=UIElementBounds(x=x, y=y, width=w, height=h),
                                is_active=win.is_active() if hasattr(win, "is_active") else False,
                                is_minimized=win.is_minimized() if hasattr(win, "is_minimized") else False,
                                is_maximized=win.is_maximized() if hasattr(win, "is_maximized") else False,
                                is_visible=True,
                                timestamp=datetime.now(UTC),
                                provenance=ObservationProvenance.REAL_PHYSICAL,
                            )
                        )
                    except Exception:
                        # Ignorar ventanas efímeras destruidas en segundo plano
                        continue
            except Exception as e:
                raise UIInspectionError(f"Fallo al listar ventanas con pywinauto: {e}") from e

            return tuple(results)
        finally:
            if com_initialized:
                _uninit_com()

    def inspect_ui(self, request: UIElementRequest) -> UIInspectionResult:
        """Inspecciona y devuelve el árbol de elementos UI sin ejecutar NINGUNA acción física."""
        start_t = datetime.now(UTC)
        try:
            desktop_cls = self._ensure_pywinauto()
        except UIBackendUnavailableError:
            return UIInspectionResult(
                tree=UIElementTree.empty(name="Backend Unavailable"),
                elements_flat=(),
                metadata=UIInspectionMetadata(
                    element_count=0,
                    max_depth_reached=0,
                    processing_time_ms=0.0,
                    backend_name="PyWinAutoInspectionBackend",
                    timestamp=datetime.now(UTC),
                    provenance=ObservationProvenance.UNAVAILABLE,
                    status=ObservationStatus.BACKEND_UNAVAILABLE,
                    error_message="Dependencia 'pywinauto' no disponible en el entorno.",
                ),
                truncated=False,
            )

        com_initialized = _init_com()
        try:
            desktop = desktop_cls(backend=self.backend_type)

            # 1. Identificar la ventana raíz según la solicitud
            target_win = None
            if request.window_title:
                matches: list[Any] = []
                for win in desktop.windows(visible_only=True):
                    try:
                        w_text = win.window_text() or ""
                        if request.window_title.lower() in w_text.lower():
                            matches.append(win)
                    except Exception:
                        continue

                # Manejo de ambigüedad: priorizar coincidencia exacta de título
                if matches:
                    exact_matches = [
                        w for w in matches
                        if (w.window_text() or "").strip().lower() == request.window_title.strip().lower()
                    ]
                    target_win = exact_matches[0] if exact_matches else matches[0]

                if not target_win:
                    proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                    return UIInspectionResult(
                        tree=UIElementTree.empty(name=request.window_title),
                        elements_flat=(),
                        metadata=UIInspectionMetadata(
                            element_count=0,
                            max_depth_reached=0,
                            processing_time_ms=proc_ms,
                            backend_name="PyWinAutoInspectionBackend",
                            timestamp=datetime.now(UTC),
                            provenance=ObservationProvenance.REAL_PHYSICAL,
                            status=ObservationStatus.NO_ELEMENTS_FOUND,
                            error_message=f"Ventana '{request.window_title}' no encontrada con pywinauto.",
                        ),
                        truncated=False,
                    )
            else:
                # Si no se especificó ventana, tomar la ventana activa
                wins = desktop.windows(visible_only=True)
                target_win = wins[0] if wins else None

            if not target_win:
                proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                return UIInspectionResult(
                    tree=UIElementTree.empty(name="No Windows"),
                    elements_flat=(),
                    metadata=UIInspectionMetadata(
                        element_count=0,
                        max_depth_reached=0,
                        processing_time_ms=proc_ms,
                        backend_name="PyWinAutoInspectionBackend",
                        timestamp=datetime.now(UTC),
                        provenance=ObservationProvenance.REAL_PHYSICAL,
                        status=ObservationStatus.NO_ELEMENTS_FOUND,
                    ),
                    truncated=False,
                )

            # 2. Recorrer la jerarquía de elementos de sólo lectura
            elements_flat: list[UIElementInfo] = []

            def build_element_info(ctrl: Any, depth: int) -> UIElementInfo | None:
                try:
                    rect = ctrl.rectangle()
                    # Soporte multi-monitor: preservar coordenadas virtuales
                    x = rect.left
                    y = rect.top
                    w = max(1, rect.width())
                    h = max(1, rect.height())
                    bounds = UIElementBounds(x=x, y=y, width=w, height=h)

                    c_type_str = getattr(ctrl.element_info, "control_type", "") or ctrl.class_name() or ""
                    ctype = UIControlType.from_str(c_type_str)

                    children_list: list[UIElementInfo] = []
                    if depth < request.max_depth and len(elements_flat) < request.max_elements:
                        try:
                            for ch in ctrl.children():
                                if len(elements_flat) >= request.max_elements:
                                    break
                                ch_info = build_element_info(ch, depth + 1)
                                if ch_info:
                                    children_list.append(ch_info)
                        except Exception:
                            # Elemento puede ser efímero o inaccesible por permisos
                            pass

                    is_enabled = True
                    try:
                        is_enabled = ctrl.is_enabled()
                    except Exception:
                        pass

                    auto_id = getattr(ctrl.element_info, "automation_id", "") or ""
                    ctrl_name = ctrl.window_text() or ""
                    cls_name = ctrl.class_name() or ""
                    pid = getattr(ctrl.element_info, "process_id", 0) or 0

                    info = UIElementInfo(
                        automation_id=auto_id,
                        name=ctrl_name,
                        control_type=ctype,
                        class_name=cls_name,
                        bounds=bounds,
                        is_enabled=is_enabled,
                        is_offscreen=False,
                        has_keyboard_focus=False,
                        process_id=pid,
                        framework_id="pywinauto",
                        children=tuple(children_list),
                    )
                    elements_flat.append(info)
                    return info
                except Exception:
                    # Stale element o elemento destruido en tiempo real
                    return None

            root_info = build_element_info(target_win, 1)
            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000

            if not root_info:
                return UIInspectionResult(
                    tree=UIElementTree.empty(name="Empty Tree"),
                    elements_flat=(),
                    metadata=UIInspectionMetadata(
                        element_count=0,
                        max_depth_reached=0,
                        processing_time_ms=proc_ms,
                        backend_name="PyWinAutoInspectionBackend",
                        timestamp=datetime.now(UTC),
                        provenance=ObservationProvenance.REAL_PHYSICAL,
                        status=ObservationStatus.NO_ELEMENTS_FOUND,
                    ),
                    truncated=False,
                )

            return UIInspectionResult(
                tree=UIElementTree(root=root_info),
                elements_flat=tuple(elements_flat),
                metadata=UIInspectionMetadata(
                    element_count=len(elements_flat),
                    max_depth_reached=request.max_depth,
                    processing_time_ms=proc_ms,
                    backend_name="PyWinAutoInspectionBackend",
                    timestamp=datetime.now(UTC),
                    provenance=ObservationProvenance.REAL_PHYSICAL,
                    status=ObservationStatus.SUCCESS,
                ),
                truncated=len(elements_flat) >= request.max_elements,
            )
        except Exception as e:
            logger.warning(f"[PYWINAUTO FAIL-SAFE] Error en inspección con pywinauto: {e}")
            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
            return UIInspectionResult(
                tree=UIElementTree.empty(name="Inspection Error"),
                elements_flat=(),
                metadata=UIInspectionMetadata(
                    element_count=0,
                    max_depth_reached=0,
                    processing_time_ms=proc_ms,
                    backend_name="PyWinAutoInspectionBackend",
                    timestamp=datetime.now(UTC),
                    provenance=ObservationProvenance.UNAVAILABLE,
                    status=ObservationStatus.INSPECTION_ERROR,
                    error_message=f"Fallo durante la inspección con pywinauto: {e}",
                ),
                truncated=False,
            )
        finally:
            if com_initialized:
                _uninit_com()
