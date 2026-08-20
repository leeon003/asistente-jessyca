"""Pruebas dedicadas para la capa de mapeo de coordenadas y DPI Awareness (Subetapa 08.4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.coordinate_mapping import (
    CoordinateMapper,
    CoordinateSpace,
    DisplayContextChangedError,
    DPIInfo,
    FakeScreenMetricsProvider,
    IncompatibleCoordinateSpaceError,
    MonitorInfo,
    OffScreenCoordinateError,
    ScreenMetrics,
)
from core.desktop_executors_models import ValidatedTarget
from core.ui_inspection_models import UIElementBounds


def make_metrics(
    monitors: list[tuple[int, int, int, int, float]],
    primary_idx: int = 0,
) -> ScreenMetrics:
    """Helper para construir métricas sintéticas de pantalla."""
    mon_list: list[MonitorInfo] = []
    min_x, min_y, max_r, max_b = 0, 0, 0, 0

    for i, (x, y, w, h, scale) in enumerate(monitors):
        dpi_val = int(96 * scale)
        bounds = UIElementBounds(x=x, y=y, width=w, height=h)
        mon = MonitorInfo(
            monitor_id=f"mon-{i}",
            device_name=f"DISPLAY_{i}",
            bounds=bounds,
            dpi=DPIInfo(dpi_x=dpi_val, dpi_y=dpi_val, scale_factor=scale),
            is_primary=(i == primary_idx),
        )
        mon_list.append(mon)
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_r = max(max_r, bounds.right)
        max_b = max(max_b, bounds.bottom)

    v_bounds = UIElementBounds(x=min_x, y=min_y, width=max_r - min_x, height=max_b - min_y)
    return ScreenMetrics(
        monitors=tuple(mon_list),
        virtual_screen_bounds=v_bounds,
        primary_monitor_id=f"mon-{primary_idx}",
        timestamp=datetime.now(UTC),
    )


def test_scale_100_percent() -> None:
    metrics = make_metrics([(0, 0, 1920, 1080, 1.0)])
    provider = FakeScreenMetricsProvider(metrics)
    mapper = CoordinateMapper(provider)

    pt = (100, 200)
    converted = mapper.convert_point(pt, CoordinateSpace.LOGICAL_DIP, CoordinateSpace.PHYSICAL_PIXELS, metrics.monitors[0])
    assert converted == (100, 200)


def test_scale_125_percent() -> None:
    metrics = make_metrics([(0, 0, 1920, 1080, 1.25)])
    provider = FakeScreenMetricsProvider(metrics)
    mapper = CoordinateMapper(provider)

    pt = (100, 200)
    converted = mapper.convert_point(pt, CoordinateSpace.LOGICAL_DIP, CoordinateSpace.PHYSICAL_PIXELS, metrics.monitors[0])
    assert converted == (125, 250)


def test_scale_150_percent() -> None:
    metrics = make_metrics([(0, 0, 1920, 1080, 1.50)])
    provider = FakeScreenMetricsProvider(metrics)
    mapper = CoordinateMapper(provider)

    pt = (100, 200)
    converted = mapper.convert_point(pt, CoordinateSpace.LOGICAL_DIP, CoordinateSpace.PHYSICAL_PIXELS, metrics.monitors[0])
    assert converted == (150, 300)


def test_scale_200_percent() -> None:
    metrics = make_metrics([(0, 0, 3840, 2160, 2.00)])
    provider = FakeScreenMetricsProvider(metrics)
    mapper = CoordinateMapper(provider)

    pt = (100, 200)
    converted = mapper.convert_point(pt, CoordinateSpace.LOGICAL_DIP, CoordinateSpace.PHYSICAL_PIXELS, metrics.monitors[0])
    assert converted == (200, 400)


def test_multi_monitor_bounds() -> None:
    # Monitor 0: Primary (0,0, 1920, 1080, 1.0)
    # Monitor 1: Secondary right (1920,0, 1920, 1080, 1.5)
    metrics = make_metrics([(0, 0, 1920, 1080, 1.0), (1920, 0, 1920, 1080, 1.5)], primary_idx=0)
    provider = FakeScreenMetricsProvider(metrics)

    mon1 = provider.get_monitor_for_point(2000, 500)
    assert mon1.monitor_id == "mon-1"
    assert mon1.dpi.scale_factor == 1.5


def test_monitor_changed_rejection() -> None:
    metrics_cap = make_metrics([(0, 0, 1920, 1080, 1.0), (1920, 0, 1920, 1080, 1.0)])  # 2 monitores
    metrics_curr = make_metrics([(0, 0, 1920, 1080, 1.0)])  # Monitor 2 desconectado

    provider = FakeScreenMetricsProvider(metrics_curr)
    mapper = CoordinateMapper(provider)

    target = ValidatedTarget(
        hwnd=1001,
        owner_title="App",
        bounds=UIElementBounds(x=100, y=100, width=50, height=30),
        confidence=0.9,
        state_hash="h1",
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(DisplayContextChangedError):
        mapper.validate_and_map_target(target, captured_metrics=metrics_cap, current_metrics=metrics_curr)


def test_target_off_screen_rejection() -> None:
    metrics = make_metrics([(0, 0, 1920, 1080, 1.0)])
    provider = FakeScreenMetricsProvider(metrics)
    mapper = CoordinateMapper(provider)

    target_off = ValidatedTarget(
        hwnd=1001,
        owner_title="App",
        bounds=UIElementBounds(x=5000, y=5000, width=50, height=30),  # Fuera de pantalla (5000, 5000)
        confidence=0.9,
        state_hash="h1",
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(OffScreenCoordinateError):
        mapper.validate_and_map_target(target_off, captured_metrics=metrics, current_metrics=metrics)


def test_dpi_changed_rejection() -> None:
    metrics_cap = make_metrics([(0, 0, 1920, 1080, 1.0)])  # Capturado a 100% DPI
    metrics_curr = make_metrics([(0, 0, 1920, 1080, 1.5)])  # Cambiado a 150% DPI

    provider = FakeScreenMetricsProvider(metrics_curr)
    mapper = CoordinateMapper(provider)

    target = ValidatedTarget(
        hwnd=1001,
        owner_title="App",
        bounds=UIElementBounds(x=100, y=100, width=50, height=30),
        confidence=0.9,
        state_hash="h1",
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(DisplayContextChangedError):
        mapper.validate_and_map_target(target, captured_metrics=metrics_cap, current_metrics=metrics_curr)


def test_incompatible_coordinate_space() -> None:
    metrics = make_metrics([(0, 0, 1920, 1080, 1.0)])
    provider = FakeScreenMetricsProvider(metrics)
    mapper = CoordinateMapper(provider)

    with pytest.raises(IncompatibleCoordinateSpaceError):
        mapper.convert_point(
            (10, 10),
            source_space="INVALID_SPACE",  # type: ignore
            target_space=CoordinateSpace.PHYSICAL_PIXELS,
            monitor=metrics.monitors[0],
        )
