"""Test Suite de Aceptación: Trazabilidad de Extremo a Extremo desde Lenguaje Natural.

Demuestra las 4 tareas reales solicitadas:
1. Abrir una carpeta ("abre la carpeta <path>")
2. Buscar información ("busca en internet información sobre computación cuántica")
3. Crear un documento ("crea un archivo de texto informe.txt con contenido...")
4. Ejecutar una tarea de varios pasos ("investiga este tema sobre IA y genera un resumen")

Trazando exhaustivamente el ciclo de vida:
Entrada (Usuario) → Core (Intent/Slots) → JDE (Gobernanza) → Herramienta (Skill) → Verificador (ExecutionVerifier) → Respuesta (Asistente)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.emergency_stop import EmergencyStopManager
from core.execution.execution_verifier import ExecutionEvidence
from core.jde.runtime_binding import JDERuntimeBinding, JDERuntimeVerdictType
from core.local_agent import (
    AgentExecutionState,
    ConversationContextManager,
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
    JessycaResponse,
)


class TestNaturalLanguageE2ETraces:
    """Demostración formal y trazada de peticiones en Lenguaje Natural."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_e2e_traces_setup")

        self.context_manager = ConversationContextManager()
        self.agent = JessycaLocalAgent(
            context_manager=self.context_manager,
            emergency_stop=self.emergency_stop,
        )
        self.agent.reset()

    # ── 1. ABRIR UNA CARPETA ──
    def test_e2e_01_open_folder_from_natural_language(self) -> None:
        """Traza: 'abre la carpeta <tmp_dir>'
        Entrada → Core (Intent: open_folder) → JDE (ALLOW) → Herramienta (windows.launch_app / explorer)
        → Verificador (gui_application_visible / folder) → Respuesta confirmada.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_folder = Path(tmp_dir) / "documentos_auditoria"
            test_folder.mkdir(parents=True, exist_ok=True)

            user_prompt = f"abre la carpeta {test_folder}"

            mock_ev = ExecutionEvidence(
                verification_type="folder_opened",
                target=str(test_folder),
                is_verified=True,
                details={"path": str(test_folder), "is_dir": True, "opened": True},
            )

            with patch("core.execution.execution_verifier.ExecutionVerifier.verify_execution", return_value=mock_ev):
                req = JessycaRequest(
                    user_input=user_prompt,
                    modality=InputModality.TEXT,
                    session_id="trace_session_folder",
                )
                resp: JessycaResponse = self.agent.interact(req)

            # 1. Entrada comprobada
            assert req.user_input == user_prompt

            # 2. Core (Detección de Intención)
            assert resp.intent in ("open_folder", "open_application")
            assert resp.selected_agent == "desktop_agent"

            # 3. Gobernanza JDE
            assert resp.security_verdict in ("ALLOW", "ALLOWED", "AUDIT")

            # 4. Herramienta invocada
            assert any(t in resp.tools_executed for t in ("windows.launch_app", "windows.open_folder", "system.coordinator"))

            # 5. Verificador y Respuesta
            assert resp.success is True
            assert resp.status == AgentExecutionState.COMPLETED
            assert len(resp.response_text) > 0

    # ── 2. BUSCAR INFORMACIÓN ──
    def test_e2e_02_search_information_from_natural_language(self) -> None:
        """Traza: 'busca en internet sobre computación cuántica'
        Entrada → Core (Intent: browser_search) → JDE (ALLOW) → Herramienta (browser.search)
        → Verificador (browser_navigated / query_submitted) → Respuesta con resultados.
        """
        user_prompt = "busca en internet sobre computación cuántica"

        mock_ev = ExecutionEvidence(
            verification_type="browser_navigated",
            target="browser",
            is_verified=True,
            details={"url": "https://www.google.com/search?q=computacion+cuantica", "verified": True},
        )

        with patch("core.execution.execution_verifier.ExecutionVerifier.verify_execution", return_value=mock_ev), \
             patch("skills.browser_search_skill.BrowserSearchSkill.ejecutar", return_value={"exito": True, "verified": True, "mensaje": "Listo, busqué 'computación cuántica' en el navegador."}):
            req = JessycaRequest(
                user_input=user_prompt,
                modality=InputModality.TEXT,
                session_id="trace_session_search",
            )
            resp: JessycaResponse = self.agent.interact(req)

        # 1. Entrada comprobada
        assert req.user_input == user_prompt

        # 2. Core (Detección de Intención)
        assert resp.intent == "browser_search"
        assert resp.selected_agent == "browser_agent"

        # 3. Gobernanza JDE
        assert resp.security_verdict in ("ALLOW", "ALLOWED", "AUDIT")

        # 4. Herramienta invocada
        assert "browser.search" in resp.tools_executed

        # 5. Verificador y Respuesta
        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert ("navegador" in resp.response_text.lower() or "computación cuántica" in resp.response_text.lower() or "busqué" in resp.response_text.lower())

    # ── 3. CREAR UN DOCUMENTO ──
    def test_e2e_03_create_document_from_natural_language(self) -> None:
        """Traza: Crear un documento y verificar su persistencia real en el disco.
        Entrada → Core (Intent: file_operation / file_creation) → JDE (ALLOW) → Herramienta (WordDocumentProcessor / FileProcessor)
        → Verificador (file_exists_on_disk con bytes > 0) → Respuesta confirmada.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            doc_file = Path(tmp_dir) / "acta_proyecto.docx"
            user_prompt = f"crea un documento word llamado {doc_file} con titulo Acta de Creacion"

            req = JessycaRequest(
                user_input=user_prompt,
                modality=InputModality.TEXT,
                session_id="trace_session_create_doc",
            )
            resp: JessycaResponse = self.agent.interact(req)

            # 1. Entrada comprobada
            assert req.user_input == user_prompt

            # 2. Core (Detección de Intención)
            assert resp.intent == "create_document"
            assert resp.selected_agent == "document_agent"

            # 3. Gobernanza JDE
            assert resp.security_verdict in ("ALLOW", "ALLOWED", "AUDIT")

            # 4. Herramienta invocada
            assert "documents.create" in resp.tools_executed

            # 5. Verificador y Respuesta
            assert resp.success is True
            assert resp.status == AgentExecutionState.COMPLETED
            assert doc_file.exists()
            assert doc_file.stat().st_size > 0

            # 6. Reapertura física del archivo Word generado
            import docx
            doc = docx.Document(str(doc_file))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            assert any("Acta de Creacion" in p or "Acta de Creación" in p for p in paragraphs)

    # ── 4. EJECUTAR TAREA DE VARIOS PASOS (ARE) ──
    def test_e2e_04_multistep_task_orchestration_from_natural_language(self) -> None:
        """Traza: 'investiga este tema sobre inteligencia artificial'
        Entrada → Core (Intent: multistep_research) → JDE (ALLOW orquestación) → Herramienta (multistep.orchestrate)
        → Verificador (plan de etapas completadas) → Respuesta sintética estructurada.
        """
        user_prompt = "investiga este tema sobre inteligencia artificial cuántica"

        req = JessycaRequest(
            user_input=user_prompt,
            modality=InputModality.TEXT,
            session_id="trace_session_multistep",
        )
        resp: JessycaResponse = self.agent.interact(req)

        # 1. Entrada comprobada
        assert req.user_input == user_prompt

        # 2. Core (Detección de Intención Multi-etapa)
        assert resp.intent == "multistep_research"
        assert resp.selected_agent == "research_coordinator_agent"

        # 3. Gobernanza JDE y Modelo
        assert resp.security_verdict in ("ALLOW", "ALLOWED", "AUDIT")
        assert resp.selected_model in ("qwen2.5-coder:7b", "gemma4:e4b", "llama3.2:3b")

        # 4. Herramienta invocada
        assert "multistep.orchestrate" in resp.tools_executed

        # 5. Verificador y Respuesta
        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert len(resp.response_text) > 0
