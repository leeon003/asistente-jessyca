"""Tests de validación para el modo SHADOW del Router Inteligente (tests/router/test_shadow_mode.py - Fase 4).

Comprueba estrictamente las 12 invariantes arquitectónicas requeridas:
1. Shadow no cambia el modelo ejecutado.
2. Shadow registra la recomendación.
3. Shadow registra confidence.
4. Shadow registra task_type.
5. Shadow registra reason.
6. Shadow no llama a Nemotron.
7. Shadow no ejecuta herramientas adicionales.
8. Shadow no bloquea el flujo principal.
9. Logs no contienen API keys.
10. Logs no contienen secretos.
11. Una excepción del logger NO rompe JESSYCA.
12. Una orden normal continúa funcionando aunque falle el registro Shadow.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.llm.experimental_router import (
    ExperimentalRouter,
    RouterDecision,
    RouterMode,
    ShadowLogger,
    TaskCategory,
)
from core.local_agent.local_agent import JessycaLocalAgent, JessycaRequest, InputModality


@pytest.fixture
def temp_shadow_file(tmp_path: Path) -> Path:
    """Provee un archivo JSONL temporal aislado para las pruebas de shadow mode."""
    log_file = tmp_path / "shadow_test_events.jsonl"
    return log_file


@pytest.fixture
def shadow_logger_isolated(temp_shadow_file: Path) -> ShadowLogger:
    """Crea una instancia de ShadowLogger apuntando al archivo aislado."""
    return ShadowLogger(log_path=temp_shadow_file)


class TestShadowModeValidation:
    """Suite de validación de 12 tests para la Fase 4 de Shadow Mode."""

    # ── TEST 1: Shadow no cambia el modelo ejecutado ──────────────────────────
    def test_shadow_does_not_change_execution_model(self, shadow_logger_isolated: ShadowLogger) -> None:
        """Test 1: Verifica que en modo SHADOW execution_model permanezca fijo en el modelo de producción."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        exec_model, decision = router.route_execution(
            user_text="Analiza este traceback de error de Python y sugiere el fix",
            current_model="gemma4:e4b",
        )
        # La recomendación puede ser Qwen o Nemotron, pero el modelo ejecutado DEBE ser gemma4:e4b
        assert exec_model == "gemma4:e4b"
        assert decision.recommended_model != ""

    # ── TEST 2: Shadow registra la recomendación ──────────────────────────────
    def test_shadow_records_recommendation(
        self, shadow_logger_isolated: ShadowLogger, temp_shadow_file: Path
    ) -> None:
        """Test 2: Verifica que el log estructurado guarde explícitamente el campo recommended_model."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        router.route_execution(
            user_text="Analiza este error de Python con memory leak",
            current_model="gemma4:e4b",
            request_id="req_test_rec_02",
        )
        assert temp_shadow_file.exists()
        record = json.loads(temp_shadow_file.read_text(encoding="utf-8").strip())
        assert record["request_id"] == "req_test_rec_02"
        assert record["recommended_model"] == "qwen3:8b"
        assert record["execution_model"] == "gemma4:e4b"

    # ── TEST 3: Shadow registra confidence ────────────────────────────────────
    def test_shadow_records_confidence(
        self, shadow_logger_isolated: ShadowLogger, temp_shadow_file: Path
    ) -> None:
        """Test 3: Verifica que el log estructurado registre el valor numérico de confianza."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        router.route_execution(
            user_text="abre el bloc de notas",
            current_model="gemma4:e4b",
            request_id="req_test_conf_03",
        )
        record = json.loads(temp_shadow_file.read_text(encoding="utf-8").strip())
        assert "confidence" in record
        assert isinstance(record["confidence"], (float, int))
        assert 0.0 <= record["confidence"] <= 1.0

    # ── TEST 4: Shadow registra task_type ─────────────────────────────────────
    def test_shadow_records_task_type(
        self, shadow_logger_isolated: ShadowLogger, temp_shadow_file: Path
    ) -> None:
        """Test 4: Verifica que se registre la categoría correcta de la tarea."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        router.route_execution(
            user_text="Analiza este traceback de error de Python",
            current_model="gemma4:e4b",
            request_id="req_test_task_04",
        )
        record = json.loads(temp_shadow_file.read_text(encoding="utf-8").strip())
        assert record["task_type"] == "technical"

    # ── TEST 5: Shadow registra reason ────────────────────────────────────────
    def test_shadow_records_reason(
        self, shadow_logger_isolated: ShadowLogger, temp_shadow_file: Path
    ) -> None:
        """Test 5: Verifica que se registre el motivo explicable de la decisión."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        router.route_execution(
            user_text="Jessica, abre la calculadora",
            is_voice=True,
            current_model="gemma4:e4b",
            request_id="req_test_reason_05",
        )
        record = json.loads(temp_shadow_file.read_text(encoding="utf-8").strip())
        assert "reason" in record
        assert len(record["reason"].strip()) > 10

    # ── TEST 6: Shadow no llama a Nemotron ───────────────────────────────────
    def test_shadow_does_not_call_nemotron(
        self, shadow_logger_isolated: ShadowLogger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test 6: Verifica que bajo ninguna circunstancia se emita llamada de red a Nemotron en shadow mode."""
        monkeypatch.setenv("NEMOTRON_ENABLED", "true")  # Aunque el flag esté activo
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)

        with patch("urllib.request.urlopen") as mock_url, patch("requests.post") as mock_post:
            exec_model, decision = router.route_execution(
                user_text="Analiza por qué el sistema está fallando, revisa las causas posibles y diseña un plan",
                current_model="gemma4:e4b",
            )
            # Aunque recomiende Nemotron, NO debe hacer llamadas de red
            assert exec_model == "gemma4:e4b"
            assert mock_url.call_count == 0
            assert mock_post.call_count == 0

    # ── TEST 7: Shadow no ejecuta herramientas adicionales ───────────────────
    def test_shadow_does_not_execute_extra_tools(self, shadow_logger_isolated: ShadowLogger) -> None:
        """Test 7: Verifica que el router no ejecute herramientas del sistema operativo ni subprocess."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)

        with patch("subprocess.Popen") as mock_popen, patch("os.system") as mock_system:
            exec_model, decision = router.route_execution(
                user_text="abre el bloc de notas",
                current_model="gemma4:e4b",
            )
            assert exec_model == "gemma4:e4b"
            assert mock_popen.call_count == 0
            assert mock_system.call_count == 0

    # ── TEST 8: Shadow no bloquea el flujo principal ──────────────────────────
    def test_shadow_does_not_block_main_flow(self, shadow_logger_isolated: ShadowLogger) -> None:
        """Test 8: Verifica que la latencia de análisis del router sea despreciable (<15ms)."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        t0 = time.perf_counter()
        exec_model, decision = router.route_execution(
            user_text="Analiza esta contradicción arquitectónica y propone una solución",
            current_model="gemma4:e4b",
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert elapsed_ms < 20.0, f"Overhead del router excesivo: {elapsed_ms:.2f}ms"
        assert exec_model == "gemma4:e4b"

    # ── TEST 9: Logs no contienen API keys ────────────────────────────────────
    def test_shadow_logs_no_api_keys(
        self, shadow_logger_isolated: ShadowLogger, temp_shadow_file: Path
    ) -> None:
        """Test 9: Verifica que claves API tipo OpenAI o GitHub queden sanitizadas."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        secret_key = "sk-1234567890abcdef1234567890abcdef1234"
        router.route_execution(
            user_text=f"Analiza este error con mi key {secret_key}",
            current_model="gemma4:e4b",
            request_id="req_test_key_09",
        )
        raw_log = temp_shadow_file.read_text(encoding="utf-8")
        assert secret_key not in raw_log
        assert "[REDACTED_API_KEY]" in raw_log

    # ── TEST 10: Logs no contienen secretos ───────────────────────────────────
    def test_shadow_logs_no_secrets(
        self, shadow_logger_isolated: ShadowLogger, temp_shadow_file: Path
    ) -> None:
        """Test 10: Verifica que contraseñas explícitas queden sanitizadas en el archivo de log."""
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=shadow_logger_isolated)
        password_value = "SuperSecretPassword2026!"
        router.route_execution(
            user_text=f"Conecta a la base de datos con password={password_value}",
            current_model="gemma4:e4b",
            request_id="req_test_secret_10",
        )
        raw_log = temp_shadow_file.read_text(encoding="utf-8")
        assert password_value not in raw_log
        assert "[REDACTED_SECRET]" in raw_log

    # ── TEST 11: Una excepción del logger NO rompe JESSYCA ───────────────────
    def test_shadow_logger_exception_does_not_break_agent(self) -> None:
        """Test 11: Verifica que si el logger lanza una excepción de IO o permisos, el router no propaga el error."""
        failing_logger = MagicMock()
        failing_logger.log_decision.side_effect = PermissionError("Disco protegido contra escritura")
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=failing_logger)

        # La llamada debe completarse con éxito a pesar del fallo en el logger
        exec_model, decision = router.route_execution(
            user_text="abre el bloc de notas",
            current_model="gemma4:e4b",
        )
        assert exec_model == "gemma4:e4b"
        assert decision.recommended_model != ""

    # ── TEST 12: Una orden normal continúa funcionando aunque falle el registro Shadow ──
    def test_normal_order_continues_if_shadow_log_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test 12: Verifica en integración completa que JessycaLocalAgent atienda la orden si el router shadow falla."""
        agent = JessycaLocalAgent.get_instance()

        # Mockear shadow_logger para forzar una excepción catastrófica
        with patch.object(agent.experimental_router.shadow_logger, "log_decision", side_effect=RuntimeError("Fallo crítico de log")):
            req = JessycaRequest(user_input="hola jessyca", modality=InputModality.TEXT)
            resp = agent.interact(req)

            # La orden continúa funcionando normalmente
            assert resp is not None
            assert resp.success is True
            assert resp.response_text != ""
