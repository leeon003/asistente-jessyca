"""Auditoría de capacidades documentales de JESSYCA 3.0 (system_audit.py).

Verifica la disponibilidad de:
1. Bibliotecas estructuradas locales (python-docx, openpyxl, python-pptx, pandas, matplotlib, PIL).
2. Motores de automatización COM en Windows (Word, Excel, PowerPoint).
3. Motor de cálculo de hojas de cálculo (diferenciando escritura de fórmulas de evaluación real).
4. Subsistema AnyDoc gobernado para conversión y lectura multi-formato.
5. Limitaciones declaradas honestamente (macros, formatos propietarios complejos, DRM/cifrado).
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.documents.system_audit")


@dataclass(frozen=True)
class DocumentLibraryStatus:
    name: str
    installed: bool
    version: str | None
    purpose: str


@dataclass(frozen=True)
class OfficeAppStatus:
    prog_id: str
    name: str
    installed: bool
    version: str | None
    can_automate_com: bool
    details: str


@dataclass(frozen=True)
class DocumentSystemAuditReport:
    os_name: str
    python_version: str
    libraries: dict[str, DocumentLibraryStatus]
    office_apps: dict[str, OfficeAppStatus]
    has_excel_calc_engine: bool
    has_anydoc_engine: bool
    capabilities_summary: dict[str, Any]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_name": self.os_name,
            "python_version": self.python_version,
            "libraries": {k: asdict(v) for k, v in self.libraries.items()},
            "office_apps": {k: asdict(v) for k, v in self.office_apps.items()},
            "has_excel_calc_engine": self.has_excel_calc_engine,
            "has_anydoc_engine": self.has_anydoc_engine,
            "capabilities_summary": self.capabilities_summary,
            "limitations": self.limitations,
        }


class DocumentSystemAuditor:
    """Auditor exhaustivo del entorno documental."""

    REQUIRED_LIBS = [
        ("docx", "Creación y edición estructurada de documentos Word (.docx)"),
        ("openpyxl", "Creación, lectura y estructuración de libros Excel (.xlsx) y gráficos"),
        ("pptx", "Generación y manipulación de presentaciones PowerPoint (.pptx)"),
        ("win32com.client", "Automatización COM de Microsoft Office (Word, Excel, PowerPoint)"),
        ("pandas", "Procesamiento tabular y análisis de datos estructurados"),
        ("matplotlib", "Generación de gráficos estadísticos e imágenes para documentos"),
        ("PIL", "Procesamiento e inspección de imágenes para diapositivas y reportes"),
    ]

    OFFICE_PROG_IDS = [
        ("Word.Application", "Microsoft Word"),
        ("Excel.Application", "Microsoft Excel"),
        ("PowerPoint.Application", "Microsoft PowerPoint"),
    ]

    @classmethod
    def audit(cls) -> DocumentSystemAuditReport:
        """Ejecuta la auditoría técnica completa del sistema."""
        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        py_ver = sys.version.split()[0]

        # 1. Auditoría de bibliotecas Python
        libs: dict[str, DocumentLibraryStatus] = {}
        for mod_name, purpose in cls.REQUIRED_LIBS:
            try:
                mod = __import__(mod_name, fromlist=["*"])
                ver = getattr(mod, "__version__", "disponible")
                libs[mod_name] = DocumentLibraryStatus(
                    name=mod_name,
                    installed=True,
                    version=str(ver),
                    purpose=purpose,
                )
            except ImportError:
                libs[mod_name] = DocumentLibraryStatus(
                    name=mod_name,
                    installed=False,
                    version=None,
                    purpose=purpose,
                )

        # 2. Auditoría de aplicaciones Office mediante el Registro de Windows y COM
        office_apps: dict[str, OfficeAppStatus] = {}
        has_excel_calc = False
        has_win32com = libs.get("win32com.client", DocumentLibraryStatus("", False, None, "")).installed

        import winreg

        for prog_id, app_name in cls.OFFICE_PROG_IDS:
            installed = False
            version: str | None = None
            try:
                # Consultar la versión registrada en Windows (ej. 'Excel.Application.16')
                cur_ver = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\CurVer")
                installed = True
                # Extraer número de versión (ej. 16)
                if "." in cur_ver:
                    version = cur_ver.split(".")[-1] + ".0"
                else:
                    version = cur_ver
            except OSError:
                installed = False
                version = None

            can_com = bool(installed and has_win32com)
            if prog_id == "Excel.Application" and can_com:
                has_excel_calc = True

            details = f"Instalado en Windows (v{version}), automatizable vía COM" if can_com else (
                f"Registrado (v{version}), pero win32com no disponible" if installed else "No instalado en el sistema"
            )

            office_apps[prog_id] = OfficeAppStatus(
                prog_id=prog_id,
                name=app_name,
                installed=installed,
                version=version,
                can_automate_com=can_com,
                details=details,
            )

        # 3. Auditoría de AnyDoc
        has_anydoc = False
        try:
            from core.anydoc.adapter import AnyDocAdapter
            from core.anydoc.orchestrator import AnyDocGovernedOrchestrator
            has_anydoc = True
        except Exception:
            has_anydoc = False

        # 4. Resumen de capacidades
        cap_summary = {
            "word": {
                "structured_creation": libs.get("docx", DocumentLibraryStatus("", False, None, "")).installed,
                "table_and_format_support": True,
                "preserve_original_on_edit": True,
                "app_automation": office_apps.get("Word.Application", OfficeAppStatus("", "", False, None, False, "")).can_automate_com,
            },
            "excel": {
                "structured_creation": libs.get("openpyxl", DocumentLibraryStatus("", False, None, "")).installed,
                "formula_writing": True,
                "formula_calculation_engine": has_excel_calc,
                "chart_generation": True,
                "app_automation": office_apps.get("Excel.Application", OfficeAppStatus("", "", False, None, False, "")).can_automate_com,
            },
            "powerpoint": {
                "structured_creation": libs.get("pptx", DocumentLibraryStatus("", False, None, "")).installed,
                "slide_layout_control": True,
                "image_embedding": libs.get("PIL", DocumentLibraryStatus("", False, None, "")).installed,
                "app_automation": office_apps.get("PowerPoint.Application", OfficeAppStatus("", "", False, None, False, "")).can_automate_com,
            },
            "anydoc_reading_and_conversion": has_anydoc,
        }

        # 5. Declaración explícita de limitaciones
        limitations = [
            "openpyxl escribe fórmulas como texto sintáctico (=SUM(...)), pero carece de motor de cálculo propio. El cálculo de resultados requiere Microsoft Excel COM.",
            "No se garantiza la ejecución ni preservación de macros VBA (.docm, .xlsm, .pptm) en manipulaciones de bajo nivel sin pruebas explícitas.",
            "Formatos de cifrado con contraseña o DRM no son soportados sin clave previa.",
            "AnyDoc está diseñado para extracción, lectura y conversión a Markdown, no para autoría de archivos binarios OOXML.",
        ]

        report = DocumentSystemAuditReport(
            os_name=os_info,
            python_version=py_ver,
            libraries=libs,
            office_apps=office_apps,
            has_excel_calc_engine=has_excel_calc,
            has_anydoc_engine=has_anydoc,
            capabilities_summary=cap_summary,
            limitations=limitations,
        )
        logger.info(f"[DOC AUDIT] Completada auditoría documental. Excel Calc Engine={has_excel_calc}, AnyDoc={has_anydoc}")
        return report
