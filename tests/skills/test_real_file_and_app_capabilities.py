"""Pruebas de capacidades reales de archivos y aplicaciones en Windows (Fase 17 / Prompt 13).

Verifica:
1. Apertura de aplicaciones instaladas (sin concatenación de shell, con verificación observable).
2. Apertura de carpetas en el Explorador de Windows.
3. Listado y localización de archivos en ubicaciones autorizadas.
4. Creación de carpetas con verificación observable (os.path.isdir).
5. Copia de archivos con preservación de contenido y prevención de sobrescritura silenciosa.
6. Mover y renombrar archivos con verificación observable.
7. Consulta de metadatos reales del sistema operativo.
8. Operaciones por lotes con vista previa obligatoria.
9. Diagnóstico de archivos abiertos o bloqueados y rechazo de rutas críticas del sistema.
10. Recorrido completo desde peticiones en lenguaje natural vía JessycaLocalAgent.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from core.application_session_manager import ApplicationSessionManager, FakeApplicationAdapter
from core.execution.execution_verifier import ExecutionStatus, get_execution_verifier
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import JessycaRequest
from skills.files_skills import (
    FilesCopySkill,
    FilesCreateFolderSkill,
    FilesListSkill,
    FilesMetadataSkill,
    FilesMoveSkill,
    FilesOrganizeSkill,
    FilesRenameSkill,
    es_ruta_critica,
)


@pytest.fixture
def workspace_temp():
    """Crea un directorio temporal aislado para pruebas de archivos reales."""
    temp_dir = tempfile.mkdtemp(prefix="jessyca_test_files_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def local_agent():
    """Instancia del agente local con FakeApplicationAdapter para pruebas deterministas."""
    fake_adapter = FakeApplicationAdapter()
    session_mgr = ApplicationSessionManager(adapter=fake_adapter)
    agent = JessycaLocalAgent()
    apps_sk = agent.skill_manager.registry.lookup("windows.apps")
    orig_session_manager = None
    if apps_sk:
        orig_session_manager = apps_sk.session_manager
        apps_sk.session_manager = session_mgr
    yield agent
    if apps_sk and orig_session_manager is not None:
        apps_sk.session_manager = orig_session_manager


# ── 1. APERTURA DE APLICACIONES INSTALADAS ──


def test_open_installed_app_end_to_end(local_agent: JessycaLocalAgent):
    """Verifica que el agente abre una aplicación instalada desde lenguaje natural."""
    req = JessycaRequest(
        session_id="sess_app_1",
        request_id="req_app_1",
        user_input="Abre el Bloc de notas",
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert resp.intent == "open_application"
    assert "notepad" in resp.response_text.lower() or "bloc" in resp.response_text.lower()


# ── 2. APERTURA DE CARPETAS EN EL EXPLORADOR ──


def test_open_folder_in_explorer_end_to_end(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica la apertura de una carpeta real en el Explorador desde lenguaje natural."""
    carpeta_objetivo = os.path.join(workspace_temp, "mi_carpeta_fotos")
    os.makedirs(carpeta_objetivo, exist_ok=True)

    prompt = f'Abre la carpeta "{carpeta_objetivo}" en el explorador'
    req = JessycaRequest(
        session_id="sess_exp_1",
        request_id="req_exp_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert resp.intent == "open_folder"
    assert "explorador" in resp.response_text.lower() or "mi_carpeta_fotos" in resp.response_text.lower()


def test_open_folder_non_existent(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica que intentar abrir una carpeta inexistente falle honestamente sin falso éxito."""
    carpeta_falsa = os.path.join(workspace_temp, "carpeta_que_no_existe_12345")

    prompt = f'Abre la carpeta "{carpeta_falsa}"'
    req = JessycaRequest(
        session_id="sess_exp_2",
        request_id="req_exp_2",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is False
    assert "no existe" in resp.response_text.lower() or "error" in resp.response_text.lower()


# ── 3. CREACIÓN DE CARPETAS CON VERIFICACIÓN OBSERVABLE ──


def test_create_folder_end_to_end(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica que crear una carpeta desde lenguaje natural la cree físicamente en disco."""
    nueva_carpeta = os.path.join(workspace_temp, "subcarpeta_nueva")
    assert not os.path.exists(nueva_carpeta)

    prompt = f'Crea la carpeta "{nueva_carpeta}"'
    req = JessycaRequest(
        session_id="sess_mkdir_1",
        request_id="req_mkdir_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert os.path.exists(nueva_carpeta)
    assert os.path.isdir(nueva_carpeta)
    assert "creada exitosamente" in resp.response_text.lower() or "subcarpeta_nueva" in resp.response_text.lower()


def test_create_folder_verification_strategy(workspace_temp: str):
    """Verifica la FolderExistsVerificationStrategy del ExecutionVerifier."""
    verifier = get_execution_verifier()
    carpeta = os.path.join(workspace_temp, "verif_dir")
    os.makedirs(carpeta, exist_ok=True)

    evidence = verifier.verify_execution("create_folder", carpeta)
    assert evidence.is_verified is True
    assert evidence.verification_type == "folder_exists"

    # Inexistente
    evidence_fail = verifier.verify_execution("create_folder", os.path.join(workspace_temp, "inexistente"))
    assert evidence_fail.is_verified is False


# ── 4. LISTADO Y LOCALIZACIÓN DE ARCHIVOS ──


def test_list_files_end_to_end(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica el listado estructurado de archivos dentro de una carpeta autorizada."""
    # Crear algunos archivos y subcarpetas reales
    file1 = os.path.join(workspace_temp, "documento1.txt")
    file2 = os.path.join(workspace_temp, "informe.pdf")
    subdir = os.path.join(workspace_temp, "sub_datos")
    with open(file1, "w", encoding="utf-8") as f:
        f.write("Contenido de prueba 1")
    with open(file2, "wb") as f:
        f.write(b"%PDF-1.4 mock pdf content")
    os.makedirs(subdir, exist_ok=True)

    prompt = f'Lista los archivos en "{workspace_temp}"'
    req = JessycaRequest(
        session_id="sess_ls_1",
        request_id="req_ls_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert resp.intent == "list_files"
    output_data = resp.output_data or {}
    elementos = output_data.get("elementos", [])
    nombres = [item["nombre"] for item in elementos]
    assert "documento1.txt" in nombres
    assert "informe.pdf" in nombres
    assert "sub_datos" in nombres


# ── 5. CONSULTA DE METADATOS ──


def test_file_metadata_end_to_end(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica la consulta de metadatos reales del SO sobre un archivo."""
    archivo = os.path.join(workspace_temp, "datos_meta.txt")
    contenido = "Texto con contenido de prueba para metadatos"
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(contenido)

    prompt = f'Consulta los metadatos de "{archivo}"'
    req = JessycaRequest(
        session_id="sess_meta_1",
        request_id="req_meta_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert resp.intent == "file_metadata"
    meta = resp.output_data.get("metadatos", {})
    assert meta["tamano_bytes"] == len(contenido.encode("utf-8"))
    assert meta["extension"] == ".txt"
    assert "fecha_modificacion" in meta
    assert meta["es_archivo"] is True


# ── 6. COPIAR ARCHIVOS CON PRESERVACIÓN DE CONTENIDO Y PREVENCIÓN DE SOBRESCRITURA ──


def test_copy_file_end_to_end_preserves_content(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica el flujo completo de copia de archivo conservando el contenido exacto."""
    origen = os.path.join(workspace_temp, "original.txt")
    destino = os.path.join(workspace_temp, "copia_original.txt")
    texto_secreto = "Contenido ultra confidencial de JESSYCA 3.0"
    with open(origen, "w", encoding="utf-8") as f:
        f.write(texto_secreto)

    prompt = f'Copia el archivo "{origen}" a "{destino}"'
    req = JessycaRequest(
        session_id="sess_cp_1",
        request_id="req_cp_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert os.path.exists(destino)
    with open(destino, "r", encoding="utf-8") as f:
        assert f.read() == texto_secreto
    assert os.path.getsize(destino) == os.path.getsize(origen)


def test_copy_prevent_silent_overwrite(workspace_temp: str):
    """Verifica que la skill FilesCopySkill NO sobrescriba silenciosamente un archivo existente."""
    skill = FilesCopySkill()
    origen = os.path.join(workspace_temp, "a.txt")
    destino = os.path.join(workspace_temp, "b.txt")
    with open(origen, "w", encoding="utf-8") as f:
        f.write("Versión 1")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("Versión Existente que NO debe perderse")

    res = skill.ejecutar({"origen": origen, "destino": destino, "sobrescribir": False})

    assert res["exito"] is False
    assert res.get("conflicto_destino") is True
    assert res.get("requiere_confirmacion") is True
    # Comprobar que el contenido del destino permanece inalterado
    with open(destino, "r", encoding="utf-8") as f:
        assert f.read() == "Versión Existente que NO debe perderse"


def test_copy_into_existing_directory(workspace_temp: str):
    """Verifica que copiar a un directorio existente resuelva correctamente la ruta destino."""
    skill = FilesCopySkill()
    origen = os.path.join(workspace_temp, "documento.pdf")
    subdir = os.path.join(workspace_temp, "carpeta_destino")
    os.makedirs(subdir, exist_ok=True)
    with open(origen, "w", encoding="utf-8") as f:
        f.write("contenido pdf")

    res = skill.ejecutar({"origen": origen, "destino": subdir})

    assert res["exito"] is True
    archivo_esperado = os.path.join(subdir, "documento.pdf")
    assert os.path.exists(archivo_esperado)
    with open(archivo_esperado, "r", encoding="utf-8") as f:
        assert f.read() == "contenido pdf"


# ── 7. MOVER Y RENOMBRAR ARCHIVOS ──


def test_move_file_end_to_end(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica mover un archivo: el destino existe y el origen desaparece."""
    origen = os.path.join(workspace_temp, "para_mover.txt")
    destino = os.path.join(workspace_temp, "movido_exito.txt")
    contenido = "Texto en tránsito"
    with open(origen, "w", encoding="utf-8") as f:
        f.write(contenido)

    prompt = f'Mueve el archivo "{origen}" a "{destino}"'
    req = JessycaRequest(
        session_id="sess_mv_1",
        request_id="req_mv_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert os.path.exists(destino)
    assert not os.path.exists(origen)
    with open(destino, "r", encoding="utf-8") as f:
        assert f.read() == contenido


def test_rename_file_end_to_end(local_agent: JessycaLocalAgent, workspace_temp: str):
    """Verifica renombrar un archivo desde lenguaje natural."""
    origen = os.path.join(workspace_temp, "nombre_antiguo.txt")
    nuevo_nombre = "nombre_actualizado.txt"
    destino_esperado = os.path.join(workspace_temp, nuevo_nombre)
    with open(origen, "w", encoding="utf-8") as f:
        f.write("Contenido que se mantiene tras renombrar")

    prompt = f'Renombra el archivo "{origen}" a "{nuevo_nombre}"'
    req = JessycaRequest(
        session_id="sess_rn_1",
        request_id="req_rn_1",
        user_input=prompt,
    )
    resp = local_agent.interact(req)

    assert resp.success is True
    assert os.path.exists(destino_esperado)
    assert not os.path.exists(origen)
    with open(destino_esperado, "r", encoding="utf-8") as f:
        assert f.read() == "Contenido que se mantiene tras renombrar"


# ── 8. VISTA PREVIA OBLIGATORIA EN OPERACIONES POR LOTES ──


def test_batch_organize_preview_mode(workspace_temp: str):
    """Verifica que organizar archivos por lotes con preview=True muestre vista previa sin ejecutar prematuramente."""
    skill = FilesOrganizeSkill()
    f1 = os.path.join(workspace_temp, "foto.jpg")
    f2 = os.path.join(workspace_temp, "texto.txt")
    with open(f1, "wb") as f:
        f.write(b"jpg content")
    with open(f2, "w", encoding="utf-8") as f:
        f.write("txt content")

    res = skill.ejecutar({"ruta_carpeta": workspace_temp, "preview": True})

    assert res["exito"] is True
    assert res.get("preview") is True
    assert res.get("requiere_confirmacion") is True
    assert res.get("total_archivos") == 2
    # Los archivos originales NO deben haber sido movidos todavía en modo vista previa
    assert os.path.exists(f1)
    assert os.path.exists(f2)


# ── 9. DIAGNÓSTICO DE ARCHIVOS BLOQUEADOS Y SEGURIDAD EN RUTAS CRÍTICAS ──


def test_critical_system_paths_blocked():
    """Verifica que rutas críticas del sistema sean denegadas deterministamente."""
    assert es_ruta_critica(r"C:\Windows") is True
    assert es_ruta_critica(r"C:\Windows\System32") is True
    assert es_ruta_critica(r"C:\Program Files") is True
    assert es_ruta_critica(r"C:\Users\PC\AppData") is True

    skill_cp = FilesCopySkill()
    res = skill_cp.ejecutar({"origen": r"C:\Windows\System32\cmd.exe", "destino": r"C:\Windows\System32\mal.exe"})
    assert res["exito"] is False
    assert any(k in res["mensaje"].lower() for k in ("crítica", "critica", "bloqueada", "protegida"))


def test_locked_file_diagnostics(workspace_temp: str):
    """Verifica que si un archivo está abierto/bloqueado, se diagnostique claramente el problema."""
    skill = FilesMoveSkill()
    src = os.path.join(workspace_temp, "archivo_bloqueado.txt")
    dst = os.path.join(workspace_temp, "destino_bloqueado.txt")
    with open(src, "w") as f:
        f.write("test")

    with patch("shutil.move", side_effect=PermissionError("El archivo está en uso por otro proceso")):
        res = skill.ejecutar({"origen": src, "destino": dst})
        assert res["exito"] is False
        assert "abierto o bloqueado" in res["mensaje"].lower() or "en uso" in res["mensaje"].lower()
