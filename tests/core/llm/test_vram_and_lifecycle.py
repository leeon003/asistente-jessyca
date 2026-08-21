"""Tests unitarios exhaustivos para VRAMGovernor y ModelLifecycleManager (Fase 3: Model Manager + VRAM Governor)."""

from unittest.mock import MagicMock

import pytest
import requests

from core.llm.exceptions import (
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.model_lifecycle import (
    ModelLifecycleManager,
    get_model_lifecycle_manager,
)
from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.llm.vram_manager import VRAMGovernor


class TestVRAMGovernor:
    """Pruebas del presupuesto de VRAM y cálculo de desalojos LRU."""

    def setup_method(self) -> None:
        ModelRegistry.reset_registry()

    def test_vram_budget_calculation(self) -> None:
        """Verifica el cálculo del presupuesto utilizable en RTX 3060 (12GB)."""
        governor = VRAMGovernor(total_vram_mb=12288, reserved_system_mb=1536)
        assert governor.usable_budget_mb == 10752

        report = governor.get_budget_report()
        assert report.total_vram_mb == 12288
        assert report.usable_budget_mb == 10752
        assert report.currently_allocated_mb == 0
        assert report.remaining_budget_mb == 10752

    def test_can_fit_when_vram_sufficient(self) -> None:
        """Verifica que un modelo quepa si hay suficiente VRAM."""
        governor = VRAMGovernor(total_vram_mb=12288, reserved_system_mb=1536)
        profile = ModelProfile(name="llama3.2", vram_estimate_mb=2500)
        assert governor.can_fit(profile) is True

    def test_eviction_plan_calculation(self) -> None:
        """Verifica que se calcule el plan de desalojo óptimo (menor prioridad / LRU primero)."""
        # Presupuesto: 8000 MB
        governor = VRAMGovernor(total_vram_mb=9536, reserved_system_mb=1536)
        # Usable = 8000 MB

        # Modelo A: 4000 MB (prioridad 1, timestamp 100)
        governor.register_loaded("modelo_a", vram_mb=4000, priority=1, timestamp=100.0)
        # Modelo B: 3000 MB (prioridad 2, timestamp 200)
        governor.register_loaded("modelo_b", vram_mb=3000, priority=2, timestamp=200.0)
        # Asignado = 7000 MB, Restante = 1000 MB

        # Queremos cargar un modelo C que requiere 5000 MB.
        # Déficit = (7000 + 5000) - 8000 = 4000 MB.
        target = ModelProfile(name="modelo_c", vram_estimate_mb=5000, priority=3)

        plan = governor.calculate_eviction_plan(target)
        # modelo_a tiene menor prioridad (1 vs 2) y libera 4000 MB, cubriendo el déficit
        assert plan == ["modelo_a"]

    def test_register_and_unregister_models(self) -> None:
        """Verifica el registro y descarga de modelos en el gobernador."""
        governor = VRAMGovernor()
        governor.register_loaded("qwen3:8b", vram_mb=5700, priority=3, timestamp=50.0)

        report1 = governor.get_budget_report()
        assert report1.currently_allocated_mb == 5700
        assert report1.loaded_models_count == 1

        unloaded = governor.register_unloaded("qwen3:8b")
        assert unloaded is True
        assert governor.get_budget_report().currently_allocated_mb == 0


class TestModelLifecycleManager:
    """Pruebas funcionales de ciclo de vida de modelos en Ollama."""

    def setup_method(self) -> None:
        ModelRegistry.reset_registry()

    def test_load_model_success(self) -> None:
        """Verifica la carga exitosa de un modelo simulando respuesta de Ollama."""
        mock_post = MagicMock()
        mock_post.return_value.status_code = 200

        governor = VRAMGovernor()
        manager = ModelLifecycleManager(
            vram_governor=governor,
            post_fn=mock_post,
        )

        success = manager.load_model("llama3.2", warmup=True)
        assert success is True
        assert manager.is_model_loaded("llama3.2") is True
        assert manager.get_active_model() == "llama3.2"
        assert "llama3.2" in manager.get_loaded_models()

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "llama3.2"
        assert kwargs["json"]["keep_alive"] == "10m"

    def test_load_model_already_loaded_no_duplicate_calls(self) -> None:
        """Verifica que si un modelo ya está cargado, no se invoque de nuevo el backend."""
        mock_post = MagicMock()
        manager = ModelLifecycleManager(post_fn=mock_post)

        # Primera carga
        manager.load_model("llama3.2")
        assert mock_post.call_count == 1

        # Segunda carga inmediata
        manager.load_model("llama3.2")
        assert mock_post.call_count == 1  # No se repite la llamada HTTP

    def test_load_model_triggers_eviction_when_vram_tight(self) -> None:
        """Verifica que cargar un modelo nuevo desaloje modelos previos si se supera el presupuesto de VRAM."""
        # Presupuesto: 6000 MB
        governor = VRAMGovernor(total_vram_mb=7536, reserved_system_mb=1536)
        mock_post = MagicMock()
        manager = ModelLifecycleManager(vram_governor=governor, post_fn=mock_post)

        # 1. Cargar llama3.1 (5500 MB)
        manager.load_model("llama3.1")
        assert manager.is_model_loaded("llama3.1") is True

        # 2. Cargar qwen3:8b (5700 MB) -> Supera los 6000 MB utilizables.
        # Debe descargar automáticamente llama3.1
        manager.load_model("qwen3:8b")

        assert manager.is_model_loaded("qwen3:8b") is True
        assert manager.is_model_loaded("llama3.1") is False

        # Verificar que se envió la llamada de descarga con keep_alive: 0
        calls = mock_post.call_args_list
        # Una de las llamadas intermedias debió ser la descarga de llama3.1
        unload_calls = [c for c in calls if c[1]["json"].get("keep_alive") == 0]
        assert len(unload_calls) >= 1
        assert unload_calls[0][1]["json"]["model"] == "llama3.1"

    def test_unload_model_explicit(self) -> None:
        """Verifica la descarga explícita de un modelo."""
        mock_post = MagicMock()
        manager = ModelLifecycleManager(post_fn=mock_post)

        manager.load_model("gemma4:e4b")
        assert manager.is_model_loaded("gemma4:e4b") is True

        manager.unload_model("gemma4:e4b")
        assert manager.is_model_loaded("gemma4:e4b") is False
        assert manager.get_active_model() is None

    def test_load_nonexistent_model_raises_error(self) -> None:
        """Verifica que solicitar un modelo no registrado falle de inmediato."""
        manager = ModelLifecycleManager()
        with pytest.raises(ModelNotFoundError):
            manager.load_model("modelo_fantasma_999")

    def test_load_connection_error_mapping(self) -> None:
        """Verifica que un fallo de red durante la carga se mapee a ProviderConnectionError."""
        mock_post = MagicMock(side_effect=requests.exceptions.ConnectionError("Refused"))
        manager = ModelLifecycleManager(post_fn=mock_post)

        with pytest.raises(ProviderConnectionError):
            manager.load_model("llama3.2")

    def test_load_timeout_error_mapping(self) -> None:
        """Verifica que un timeout durante la carga se mapee a ProviderTimeoutError."""
        mock_post = MagicMock(side_effect=requests.exceptions.Timeout("Timeout"))
        manager = ModelLifecycleManager(post_fn=mock_post)

        with pytest.raises(ProviderTimeoutError):
            manager.load_model("llama3.2", timeout_seconds=2.0)

    def test_health_check_reporting(self) -> None:
        """Verifica el reporte del chequeo de salud integral."""
        mock_get = MagicMock()
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.side_effect = [
            {"models": [{"name": "llama3.2:latest"}, {"name": "qwen3:8b"}]},  # /api/tags
            {"models": [{"name": "qwen3:8b", "size_vram": 5976883200}]},      # /api/ps
        ]
        mock_get.return_value = mock_get_resp

        manager = ModelLifecycleManager(get_fn=mock_get)
        health = manager.health_check()

        assert health["server_healthy"] is True
        assert "llama3.2:latest" in health["installed_models_on_disk"]
        assert "vram_budget" in health
        assert health["vram_budget"]["total_mb"] == 12288

    def test_singleton_accessor(self) -> None:
        """Verifica la función helper get_model_lifecycle_manager()."""
        m1 = get_model_lifecycle_manager()
        m2 = ModelLifecycleManager.get_instance()
        assert m1 is m2
