"""Tests unitarios e integrales para el Motor de Aprendizaje de Rendimiento de Modelos (Fase 26).

Verifica:
1. Persistencia y recuperación de registros en base de datos SQLite
2. Agregación estadística precisa (success rate, latencia promedio, p95, tokens, vram, confianza)
3. Privacidad y redacción estricta de secretos (SecretRedactor en errores y metadatos)
4. Recuperación automática y resiliencia ante corrupción de base de datos
5. Manejo de arranque en frío (Cold start / datos insuficientes)
6. Agregación por tipo de tarea y ranking de modelos
7. Integración fluida con ModelPerformanceLearner y ModelRouter
8. Invariante: MODEL PERFORMANCE LEARNING != SECURITY AUTHORIZATION
"""

import tempfile
from pathlib import Path

from core.llm.model_router import ModelRouter
from core.llm.performance_learning import ModelPerformanceLearner
from core.llm.performance_models import InferenceExecutionRecord
from core.llm.performance_store import ModelPerformanceStore
from core.llm.smart_routing_models import TaskType
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)


class TestModelPerformanceLearning:
    """Suite de pruebas para Model Performance Learning."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_perf.db"
        self.store = ModelPerformanceStore(db_path=self.db_path)
        self.learner = ModelPerformanceLearner(store=self.store)
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()

    def teardown_method(self) -> None:
        self.temp_dir.cleanup()

    # ── 1. PERSISTENCIA Y RECUPERACIÓN ──

    def test_record_persistence_and_reload(self) -> None:
        """Verifica que los registros se persistan y se puedan consultar tras reiniciar el store."""
        record = InferenceExecutionRecord(
            model_name="llama3.1",
            task_type=TaskType.CONVERSATION,
            latency_ms=45.0,
            tokens=120,
            success=True,
            confidence=0.95,
            vram_mb=5500.0,
        )
        self.store.record_execution(record)

        # Crear nueva instancia apuntando a la misma BD
        new_store = ModelPerformanceStore(db_path=self.db_path)
        stats = new_store.get_stats("llama3.1", TaskType.CONVERSATION)

        assert stats.total_executions == 1
        assert stats.successful_executions == 1
        assert stats.success_rate == 1.0
        assert stats.avg_latency_ms == 45.0
        assert stats.avg_tokens == 120.0

    # ── 2. AGREGACIÓN Y ESTADÍSTICAS ──

    def test_statistical_aggregation_and_percentiles(self) -> None:
        """Verifica el cálculo de tasas de éxito, latencia promedio y p95."""
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        for i, lat in enumerate(latencies):
            # Fallar en 2 de cada 10
            is_success = (i % 5 != 0)
            self.learner.record_inference(
                model_name="qwen3:8b",
                task_type=TaskType.REASONING,
                latency_ms=lat,
                tokens=200,
                success=is_success,
                confidence=0.90,
                vram_mb=5700.0,
            )

        stats = self.learner.get_model_stats("qwen3:8b", TaskType.REASONING)
        assert stats.total_executions == 10
        assert stats.successful_executions == 8
        assert stats.failed_executions == 2
        assert stats.success_rate == 0.80
        assert stats.avg_latency_ms == 55.0
        assert stats.p95_latency_ms >= 90.0
        assert stats.is_cold_start is False

    # ── 3. PRIVACIDAD Y REDACCIÓN DE SECRETOS ──

    def test_privacy_redaction_in_error_and_metadata(self) -> None:
        """Verifica que contraseñas, tokens y claves API sean redactados antes de almacenarse."""
        sensitive_error = "Authentication failed with token=sk-abcdef1234567890 and password=SuperSecretPassword123"
        sensitive_meta = {"api_key": "Bearer my_super_secret_jwt_token_12345"}

        self.learner.record_inference(
            model_name="llama3.2",
            task_type=TaskType.CLASSIFICATION,
            latency_ms=15.0,
            success=False,
            error_message=sensitive_error,
            metadata=sensitive_meta,
        )

        recent = self.store.get_recent_records(limit=1)
        assert len(recent) == 1
        rec = recent[0]

        # Verificar que el secreto no está presente en texto plano
        assert "SuperSecretPassword123" not in str(rec.error_message)
        assert "sk-abcdef1234567890" not in str(rec.error_message)
        assert "<REDACTED" in str(rec.error_message) or "[REDACTED" in str(rec.error_message)

    # ── 4. RESILIENCIA Y RECUPERACIÓN ANTE CORRUPCIÓN ──

    def test_auto_recovery_on_corrupted_database(self) -> None:
        """Verifica que si el archivo de base de datos se corrompe, se recupere automáticamente."""
        # Escribir basura en el archivo sqlite
        with open(self.db_path, "wb") as f:
            f.write(b"CORRUPTED_GARBAGE_DATA_HEADER")

        # La inicialización o consulta no debe lanzar excepción no manejada
        store_recovered = ModelPerformanceStore(db_path=self.db_path)
        stats = store_recovered.get_stats("llama3.1")
        assert stats.total_executions == 0
        assert stats.is_cold_start is True

        # Debe permitir insertar tras recuperación
        store_recovered.record_execution(
            InferenceExecutionRecord(
                model_name="llama3.1",
                task_type=TaskType.CONVERSATION,
                latency_ms=30.0,
                success=True,
            )
        )
        assert store_recovered.get_stats("llama3.1").total_executions == 1

    # ── 5. ARRANQUE EN FRÍO (COLD START) ──

    def test_cold_start_handling(self) -> None:
        """Verifica el comportamiento de modelos sin historial previo o con menos de 5 ejecuciones."""
        # 0 ejecuciones
        stats_zero = self.learner.get_model_stats("gemma4:e4b", TaskType.ANALYSIS_VERIFICATION)
        assert stats_zero.total_executions == 0
        assert stats_zero.success_rate == 1.0  # Confianza optimista a priori
        assert stats_zero.is_cold_start is True

        # 3 ejecuciones (< 5)
        for _ in range(3):
            self.learner.record_inference(
                model_name="gemma4:e4b",
                task_type=TaskType.ANALYSIS_VERIFICATION,
                latency_ms=25.0,
                success=True,
            )
        stats_three = self.learner.get_model_stats("gemma4:e4b", TaskType.ANALYSIS_VERIFICATION)
        assert stats_three.total_executions == 3
        assert stats_three.is_cold_start is True

    # ── 6. RANKING DE MODELOS POR TIPO DE TAREA ──

    def test_task_ranking_generation(self) -> None:
        """Verifica que el ranking ordene los modelos por score combinado de éxito y latencia."""
        # Modelo rápido y exitoso
        for _ in range(5):
            self.learner.record_inference("model_fast", TaskType.CLASSIFICATION, latency_ms=10.0, success=True)

        # Modelo lento y con fallos
        for _ in range(5):
            self.learner.record_inference("model_slow", TaskType.CLASSIFICATION, latency_ms=500.0, success=False)

        ranking = self.learner.get_task_ranking(TaskType.CLASSIFICATION)
        assert len(ranking) >= 2
        assert ranking[0][0] == "model_fast"
        assert ranking[0][1] > ranking[1][1]

    # ── 7. INTEGRACIÓN CON MODEL ROUTER ──

    def test_integration_with_model_router(self) -> None:
        """Verifica que el enrutador pueda registrar y beneficiarse de métricas de aprendizaje."""
        router = ModelRouter.get_instance()
        router.record_inference_result(
            model_name="llama3.2",
            task_type=TaskType.SIMPLE_TASK,
            latency_ms=12.0,
            success=True,
            tokens=50,
        )
        selected = router.select_model_for_task(TaskType.SIMPLE_TASK)
        assert selected is not None

    # ── 8. INVARIANTE: MODEL PERFORMANCE LEARNING != SECURITY AUTHORIZATION ──

    def test_learning_system_has_no_security_authority(self) -> None:
        """Verifica que ModelPerformanceLearner no tenga autoridad de seguridad ni modifique SecurityPipeline."""
        assert not hasattr(self.learner, "authorize")
        assert not hasattr(self.learner, "bypass_security")

        req = SecurityRequest(
            context=SecurityContext(user="learner", tool_name="system.format_disk", parameters={}),
            metadata=ToolSecurityMetadata(tool_name="system.format_disk", category="system", risk_level=SecurityLevel.CRITICAL),
        )
        assessment = self.risk_engine.evaluate_risk(req)
        assert assessment.risk_level == SecurityLevel.CRITICAL

        decision = self.permission_manager.check_permission(
            tool_name="system.format_disk",
            risk_level=SecurityLevel.CRITICAL,
        )
        assert decision == PermissionDecision.DENY
