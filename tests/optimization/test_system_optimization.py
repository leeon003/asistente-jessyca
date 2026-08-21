"""Tests unitarios para el Sistema de Optimización (Fase 18: System Optimization).

Verifica:
1. Safe Caching para consultas deterministas
2. Bloqueo estricto de almacenamiento de credenciales o secretos en caché
3. Expiración de entradas por TTL y desalojo LRU
4. Evaluación de co-residencia de modelos en 12 GB de VRAM (RTX 3060)
5. Detección y mitigación de thrashing en VRAM
6. Gating de consenso selectivo para reducción de inferencias redundantes
"""

import time

from core.optimization import (
    SafeCache,
    VRAMOptimizer,
)


class TestSystemOptimization:
    """Suite de pruebas de optimización de latencia, caché seguro y VRAM."""

    def setup_method(self) -> None:
        self.cache = SafeCache(max_entries=3, default_ttl_seconds=1.0)
        self.vram_optimizer = VRAMOptimizer()

    # ── 1. SAFE CACHING DE DATOS SEGUROS ──

    def test_safe_cache_hit_and_miss(self) -> None:
        """Verifica almacenamiento y recuperación de datos no sensibles."""
        query = "specs de memoria RAM del sistema"
        data = {"ram_total_gb": 16, "ram_free_gb": 8}

        assert self.cache.get(query) is None
        assert self.cache.set(query, data) is True
        assert self.cache.get(query) == data

    # ── 2. BLOQUEO DE SECRETOS EN CACHÉ ──

    def test_sensitive_data_cache_denied(self) -> None:
        """Verifica que contraseñas, tokens y cookies sean rechazados por SafeCache."""
        assert self.cache.set("login_pass", "Password123!") is False
        assert self.cache.set("bearer_token", "Bearer eyJhbGciOiJIUz...") is False
        assert self.cache.set("session_cookie", "cookie: session_id=123") is False
        assert self.cache.size() == 0

    # ── 3. TTL Y LRU EVICTION EN CACHÉ ──

    def test_cache_ttl_expiration(self) -> None:
        """Verifica que las entradas caduquen tras su tiempo de vida TTL."""
        self.cache.set("key_temp", "temp_value", ttl_seconds=0.05)
        assert self.cache.get("key_temp") == "temp_value"

        time.sleep(0.12)
        assert self.cache.get("key_temp") is None

    def test_cache_lru_eviction(self) -> None:
        """Verifica el desalojo de la entrada menos recientemente usada al alcanzar la capacidad."""
        self.cache.set("k1", "v1")
        self.cache.set("k2", "v2")
        self.cache.set("k3", "v3")

        # Acceder a k1 para marcarlo como recientemente usado
        _ = self.cache.get("k1")

        # Agregar k4 debe desalojar k2 (la más antigua no accedida)
        self.cache.set("k4", "v4")

        assert self.cache.get("k1") == "v1"
        assert self.cache.get("k2") is None
        assert self.cache.get("k3") == "v3"
        assert self.cache.get("k4") == "v4"

    # ── 4. VRAM CO-RESIDENCY EVALUATION (RTX 3060 12GB) ──

    def test_vram_co_residency_plans(self) -> None:
        """Verifica el cálculo de residencia conjunta en 10,752 MB de VRAM utilizable."""
        # 1. Combinación segura: qwen3:8b (6000MB) + gemma4:e4b (3800MB) = 9800MB <= 10752MB
        plan_safe = self.vram_optimizer.evaluate_co_residency(["qwen3:8b", "gemma4:e4b"])
        assert plan_safe.is_safe is True
        assert plan_safe.total_allocated_mb == 9800

        # 2. Combinación insegura (OOM): llama3.1:latest (8000MB) + qwen3:8b (6000MB) = 14000MB > 10752MB
        plan_unsafe = self.vram_optimizer.evaluate_co_residency(["llama3.1:latest", "qwen3:8b"])
        assert plan_unsafe.is_safe is False
        assert plan_unsafe.total_allocated_mb == 14000

    # ── 5. ANTI-THRASHING DETECTION ──

    def test_vram_anti_thrashing(self) -> None:
        """Verifica la detección de riesgo de thrashing tras desalojos recientes."""
        model = "llama3.1:latest"
        assert self.vram_optimizer.is_thrashing_risk(model) is False

        self.vram_optimizer.record_eviction(model)
        assert self.vram_optimizer.is_thrashing_risk(model) is True

    # ── 6. SELECTIVE CONSENSUS GATING ──

    def test_selective_consensus_gating(self) -> None:
        """Verifica que el consenso se active sólo ante confianza moderada/baja para ahorrar inferencias."""
        # Alta confianza (0.95 >= 0.85) -> No necesita consenso
        assert self.vram_optimizer.should_trigger_consensus(0.95) is False

        # Baja confianza (0.60 < 0.85) -> Requiere consenso multi-modelo
        assert self.vram_optimizer.should_trigger_consensus(0.60) is True
