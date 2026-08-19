"""Tests del MetricCollector — Etapa 17.0.

Verifica:
- Counter: increment, no-decrement
- Histogram: observe, count, sum, mean, buckets
- Gauge: set, increment, decrement
- MetricCollector: todas las métricas pre-registradas
- record_* API de conveniencia
- snapshot() formato correcto
- Sink registration
"""

from __future__ import annotations

import threading

import pytest

from core.observability.metric_collector import MetricCollector
from core.observability.metric_models import Counter, Gauge, Histogram


class TestCounter:
    def test_starts_at_zero(self) -> None:
        c = Counter(name="test_counter")
        assert c.value == 0.0

    def test_increment_by_one(self) -> None:
        c = Counter(name="test_counter")
        c.increment()
        assert c.value == 1.0

    def test_increment_by_amount(self) -> None:
        c = Counter(name="test_counter")
        c.increment(5.0)
        assert c.value == 5.0

    def test_cannot_decrement(self) -> None:
        c = Counter(name="test_counter")
        with pytest.raises(ValueError, match="decrementarse"):
            c.increment(-1.0)

    def test_thread_safe_increment(self) -> None:
        c = Counter(name="thread_counter")
        threads = [threading.Thread(target=lambda: c.increment()) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.value == 100.0

    def test_to_dict(self) -> None:
        c = Counter(name="my_counter", help="test help")
        c.increment(3.0)
        d = c.to_dict()
        assert d["type"] == "counter"
        assert d["name"] == "my_counter"
        assert d["value"] == 3.0


class TestHistogram:
    def test_starts_at_zero_count(self) -> None:
        h = Histogram(name="test_hist", buckets=[10.0, 100.0, 1000.0])
        assert h.count == 0
        assert h.sum == 0.0

    def test_observe_increments_count_and_sum(self) -> None:
        h = Histogram(name="test_hist", buckets=[10.0, 100.0])
        h.observe(50.0)
        assert h.count == 1
        assert h.sum == 50.0

    def test_mean_calculation(self) -> None:
        h = Histogram(name="test_hist", buckets=[100.0])
        h.observe(10.0)
        h.observe(30.0)
        assert h.mean == 20.0

    def test_mean_none_when_empty(self) -> None:
        h = Histogram(name="test_hist", buckets=[100.0])
        assert h.mean is None

    def test_bucket_counts(self) -> None:
        h = Histogram(name="test_hist", buckets=[10.0, 50.0, 100.0, float("inf")])
        h.observe(5.0)   # en bucket <=10
        h.observe(40.0)  # en buckets <=50 y <=100 y <=inf
        h.observe(75.0)  # en buckets <=100 y <=inf
        d = h.to_dict()
        # 5.0 <= 10 → bucket 10 debería tener 1 (solo 5.0)
        assert d["buckets"]["10.0"] == 1
        # 5.0 y 40.0 <= 50 → bucket 50 debería tener 2
        assert d["buckets"]["50.0"] == 2

    def test_thread_safe_observe(self) -> None:
        h = Histogram(name="thread_hist", buckets=[float("inf")])
        threads = [threading.Thread(target=lambda: h.observe(1.0)) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert h.count == 50
        assert h.sum == 50.0


class TestGauge:
    def test_starts_at_zero(self) -> None:
        g = Gauge(name="test_gauge")
        assert g.value == 0.0

    def test_set(self) -> None:
        g = Gauge(name="test_gauge")
        g.set(42.0)
        assert g.value == 42.0

    def test_increment_and_decrement(self) -> None:
        g = Gauge(name="test_gauge")
        g.increment(5.0)
        assert g.value == 5.0
        g.decrement(2.0)
        assert g.value == 3.0

    def test_can_go_negative(self) -> None:
        g = Gauge(name="test_gauge")
        g.decrement(10.0)
        assert g.value == -10.0

    def test_to_dict(self) -> None:
        g = Gauge(name="sessions", help="active sessions")
        g.set(7.0)
        d = g.to_dict()
        assert d["type"] == "gauge"
        assert d["value"] == 7.0
        assert "updated_at" in d


class TestMetricCollector:
    def _fresh(self) -> MetricCollector:
        return MetricCollector()

    def test_all_metrics_pre_registered(self) -> None:
        mc = self._fresh()
        # Counters
        assert mc.requests_total.name == "jessyca_requests_total"
        assert mc.security_denials_total.name == "jessyca_security_denials_total"
        assert mc.confirmations_total.name == "jessyca_confirmations_total"
        assert mc.emergency_stops_total.name == "jessyca_emergency_stops_total"
        assert mc.plugin_executions_total.name == "jessyca_plugin_executions_total"
        assert mc.audit_events_total.name == "jessyca_audit_events_total"
        assert mc.errors_total.name == "jessyca_errors_total"
        # Histograms
        assert mc.request_duration_ms.name == "jessyca_request_duration_ms"
        # Gauges
        assert mc.active_sessions.name == "jessyca_active_sessions"
        assert mc.emergency_stop_active.name == "jessyca_emergency_stop_active"

    def test_record_request(self) -> None:
        mc = self._fresh()
        mc.record_request("registry.write", "write", "success")
        assert mc.requests_total.value == 1.0

    def test_record_security_denial(self) -> None:
        mc = self._fresh()
        mc.record_security_denial("BLACKLIST", "CRITICAL")
        assert mc.security_denials_total.value == 1.0

    def test_record_emergency_stop_sets_gauge(self) -> None:
        mc = self._fresh()
        mc.record_emergency_stop()
        assert mc.emergency_stops_total.value == 1.0
        assert mc.emergency_stop_active.value == 1.0

    def test_record_emergency_stop_reset_clears_gauge(self) -> None:
        mc = self._fresh()
        mc.record_emergency_stop()
        mc.record_emergency_stop_reset()
        assert mc.emergency_stop_active.value == 0.0

    def test_observe_request_duration(self) -> None:
        mc = self._fresh()
        mc.observe_request_duration(250.0)
        assert mc.request_duration_ms.count == 1
        assert mc.request_duration_ms.sum == 250.0

    def test_record_plugin_execution(self) -> None:
        mc = self._fresh()
        mc.record_plugin_execution("my-plugin", "success", 150.0)
        assert mc.plugin_executions_total.value == 1.0
        assert mc.plugin_execution_duration_ms.count == 1

    def test_record_error(self) -> None:
        mc = self._fresh()
        mc.record_error("boundary.registry", "RegistrySecurityViolationError")
        assert mc.errors_total.value == 1.0

    def test_snapshot_structure(self) -> None:
        mc = self._fresh()
        snap = mc.snapshot()
        assert "counters" in snap
        assert "histograms" in snap
        assert "gauges" in snap
        assert "requests_total" in snap["counters"]
        assert "request_duration_ms" in snap["histograms"]
        assert "active_sessions" in snap["gauges"]

    def test_sink_receives_flush(self) -> None:
        received = []

        class FakeSink:
            def emit(self, snapshot):  # type: ignore[no-untyped-def]
                received.append(snapshot)

        mc = self._fresh()
        mc.register_sink(FakeSink())
        mc.record_request("tool", "op", "ok")
        mc.flush_to_sinks()
        assert len(received) == 1
        assert "counters" in received[0]
