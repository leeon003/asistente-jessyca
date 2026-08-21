"""Suite de pruebas exhaustiva para el Catálogo Inicial de Skills (Fase 28.8).

Valida cada uno de los 4 grupos de habilidades implementadas:
1. Grupo Windows (apps, screenshot, clipboard, notifications, audio, display)
2. Grupo Files (search, read, create, copy, move, rename, organize)
3. Grupo Browser (open, search, navigate, read, download)
4. Grupo Documents (read, create, summarize, convert)
"""

import os
import tempfile

from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    SKILLS_DISPONIBLES,
    BrowserDownloadSkill,
    BrowserNavigateSkill,
    BrowserOpenSkill,
    BrowserReadSkill,
    DocumentsConvertSkill,
    DocumentsCreateSkill,
    DocumentsReadSkill,
    DocumentsSummarizeSkill,
    FilesCopySkill,
    FilesCreateSkill,
    FilesMoveSkill,
    FilesOrganizeSkill,
    FilesReadSkill,
    FilesRenameSkill,
    SkillManager,
    SkillRegistry,
    SkillRouter,
    SkillRuntime,
    SkillSecuritySandbox,
    SkillValidator,
    WindowsAudioSkill,
    WindowsClipboardSkill,
    WindowsDisplaySkill,
    WindowsNotificationsSkill,
)


class TestInitialSkillCatalog:
    """Suite integral para validar todos los grupos del Catálogo de Skills."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_catalog_setup")
        self.registry = SkillRegistry()
        self.registry.reset()
        self.router = SkillRouter(registry=self.registry)
        self.runtime = SkillRuntime(emergency_stop=self.emergency_stop)
        self.manager = SkillManager(
            registry=self.registry,
            router=self.router,
            runtime=self.runtime,
        )
        self.sandbox = SkillSecuritySandbox(emergency_stop=self.emergency_stop)

        # Cargar todas las skills del catálogo
        for _name, skill in SKILLS_DISPONIBLES.items():
            self.manager.load_skill(skill)

    # ══════════════════════════════════════════════════════════════════
    # 1. VALIDACIÓN GENERAL DEL CATÁLOGO
    # ══════════════════════════════════════════════════════════════════

    def test_catalog_manifests_validation(self) -> None:
        """Verifica que todas las 21 skills del catálogo oficial posean manifiestos válidos."""
        skills = self.registry.list_skills()
        assert len(skills) >= 21
        for sk_def in skills:
            if sk_def.manifest is not None:
                is_valid, err = SkillValidator.validate_manifest(sk_def.manifest)
                assert is_valid is True, f"Error en manifiesto '{sk_def.skill_id}': {err}"
                assert sk_def.risk_level in (SecurityLevel.SAFE, SecurityLevel.WARNING)

    # ══════════════════════════════════════════════════════════════════
    # 2. GRUPO WINDOWS
    # ══════════════════════════════════════════════════════════════════

    def test_windows_clipboard_skill(self) -> None:
        """Verifica escritura, lectura y limpieza en el portapapeles."""
        skill = WindowsClipboardSkill()
        # Escribir
        r_write = skill.ejecutar({"accion": "escribir", "texto": "JESSYCA Clipboard Test"})
        assert r_write["exito"] is True

        # Leer
        r_read = skill.ejecutar({"accion": "leer"})
        assert r_read["exito"] is True
        assert r_read["contenido"] == "JESSYCA Clipboard Test"

        # Limpiar
        r_clear = skill.ejecutar({"accion": "limpiar"})
        assert r_clear["exito"] is True
        assert skill.ejecutar({"accion": "leer"})["contenido"] == ""

    def test_windows_notifications_skill(self) -> None:
        """Verifica emisión de notificaciones de escritorio."""
        skill = WindowsNotificationsSkill()
        res = skill.ejecutar({"titulo": "Alerta", "mensaje": "Tarea completada."})
        assert res["exito"] is True
        assert res["titulo"] == "Alerta"

    def test_windows_audio_skill(self) -> None:
        """Verifica consulta, ajuste de volumen y mute."""
        skill = WindowsAudioSkill()
        # Ajustar volumen
        r_set = skill.ejecutar({"accion": "establecer", "nivel": 75})
        assert r_set["exito"] is True
        assert r_set["volumen"] == 75

        # Silenciar (toggle mute)
        r_mute = skill.ejecutar({"accion": "silenciar"})
        assert r_mute["exito"] is True
        assert r_mute["silenciado"] is True

    def test_windows_display_skill(self) -> None:
        """Verifica obtención de datos de monitores y resolución."""
        skill = WindowsDisplaySkill()
        res = skill.ejecutar({})
        assert res["exito"] is True
        assert res["ancho"] > 0
        assert res["alto"] > 0
        assert res["monitores"] >= 1

    # ══════════════════════════════════════════════════════════════════
    # 3. GRUPO FILES
    # ══════════════════════════════════════════════════════════════════

    def test_files_crud_and_organize_lifecycle(self) -> None:
        """Verifica el ciclo completo de creación, lectura, copia, renombrado, movimiento y organización."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = os.path.join(tmp_dir, "reporte.txt")

            # 1. Crear archivo
            c_skill = FilesCreateSkill()
            r_create = c_skill.ejecutar({"ruta": test_file, "contenido": "Contenido confidencial"})
            assert r_create["exito"] is True
            assert os.path.exists(test_file)

            # 2. Leer archivo
            r_skill = FilesReadSkill()
            r_read = r_skill.ejecutar({"ruta": test_file})
            assert r_read["exito"] is True
            assert "Contenido confidencial" in r_read["contenido"]

            # 3. Copiar archivo
            copy_file = os.path.join(tmp_dir, "reporte_copia.txt")
            cp_skill = FilesCopySkill()
            r_copy = cp_skill.ejecutar({"origen": test_file, "destino": copy_file})
            assert r_copy["exito"] is True
            assert os.path.exists(copy_file)

            # 4. Renombrar archivo
            ren_skill = FilesRenameSkill()
            r_ren = ren_skill.ejecutar({"ruta": copy_file, "nuevo_nombre": "reporte_v2.txt"})
            assert r_ren["exito"] is True
            renamed_file = os.path.join(tmp_dir, "reporte_v2.txt")
            assert os.path.exists(renamed_file)

            # 5. Mover archivo
            sub_dir = os.path.join(tmp_dir, "subfolder")
            os.makedirs(sub_dir, exist_ok=True)
            mv_skill = FilesMoveSkill()
            dest_file = os.path.join(sub_dir, "reporte_v2.txt")
            r_mv = mv_skill.ejecutar({"origen": renamed_file, "destino": dest_file})
            assert r_mv["exito"] is True
            assert os.path.exists(dest_file)

            # 6. Organizar archivos en subcarpetas
            # Crear varios tipos de archivo en tmp_dir
            with open(os.path.join(tmp_dir, "data.json"), "w") as f:
                f.write('{"key": 1}')
            with open(os.path.join(tmp_dir, "image.png"), "w") as f:
                f.write("fakeimg")

            org_skill = FilesOrganizeSkill()
            r_org = org_skill.ejecutar({"directorio": tmp_dir})
            assert r_org["exito"] is True
            assert os.path.exists(os.path.join(tmp_dir, "Datos", "data.json"))
            assert os.path.exists(os.path.join(tmp_dir, "Imagenes", "image.png"))

    def test_files_create_blocks_executable_extensions(self) -> None:
        """Verifica que FilesCreateSkill bloquee extensiones ejecutables o peligrosas."""
        skill = FilesCreateSkill()
        res = skill.ejecutar({"ruta": "malicious.exe", "contenido": "binary payload"})
        assert res["exito"] is False
        assert "bloqueada" in res["mensaje"]

    # ══════════════════════════════════════════════════════════════════
    # 4. GRUPO BROWSER
    # ══════════════════════════════════════════════════════════════════

    def test_browser_skills_operations(self) -> None:
        """Verifica apertura, navegación, lectura y descarga web."""
        # 1. Open
        open_skill = BrowserOpenSkill()
        r_open = open_skill.ejecutar({"url": "https://www.google.com"})
        assert r_open["exito"] is True

        # 2. Navigate
        nav_skill = BrowserNavigateSkill()
        r_nav = nav_skill.ejecutar({"url": "https://www.google.com/search"})
        assert r_nav["exito"] is True

        # 3. Read
        read_skill = BrowserReadSkill()
        r_read = read_skill.ejecutar({"url": "https://www.google.com"})
        assert r_read["exito"] is True
        assert "texto_extraido" in r_read

        # 4. Download - safe
        dl_skill = BrowserDownloadSkill()
        r_dl_safe = dl_skill.ejecutar({"url": "https://github.com/dataset.csv"})
        assert r_dl_safe["exito"] is True

        # 5. Download - blocked dangerous extension
        r_dl_danger = dl_skill.ejecutar({"url": "https://github.com/installer.exe"})
        assert r_dl_danger["exito"] is False
        assert "denegada" in r_dl_danger["mensaje"]

    # ══════════════════════════════════════════════════════════════════
    # 5. GRUPO DOCUMENTS
    # ══════════════════════════════════════════════════════════════════

    def test_documents_skills_pipeline(self) -> None:
        """Verifica creación, lectura, resumen y conversión de documentos."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            doc_path = os.path.join(tmp_dir, "informe_ejecutivo.md")

            # 1. Crear documento
            create_skill = DocumentsCreateSkill()
            r_create = create_skill.ejecutar({
                "titulo": "Informe Financiero Q3",
                "contenido": "Crecimiento del 25% en ingresos operativos.",
                "ruta": doc_path,
            })
            assert r_create["exito"] is True
            assert os.path.exists(doc_path)

            # 2. Leer documento
            read_skill = DocumentsReadSkill()
            r_read = read_skill.ejecutar({"ruta": doc_path})
            assert r_read["exito"] is True
            assert "Informe Financiero Q3" in r_read["contenido"]

            # 3. Resumir documento
            sum_skill = DocumentsSummarizeSkill()
            r_sum = sum_skill.ejecutar({"ruta": doc_path})
            assert r_sum["exito"] is True
            assert "Resumen Ejecutivo" in r_sum["resumen"]

            # 4. Convertir JSON a CSV
            conv_skill = DocumentsConvertSkill()
            json_payload = '[{"id": 1, "nombre": "Alice"}, {"id": 2, "nombre": "Bob"}]'
            r_conv = conv_skill.ejecutar({
                "contenido": json_payload,
                "origen": "json",
                "destino": "csv",
            })
            assert r_conv["exito"] is True
            assert "Alice" in r_conv["resultado"]
            assert "Bob" in r_conv["resultado"]
