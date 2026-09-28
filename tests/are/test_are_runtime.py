"""Tests for ARE Runtime Modes and Lifecycle."""

import pytest
from pydantic import ValidationError

from config.settings import AppSettings
from core.are.models import ARERuntimeMode
from core.are.runtime import ARERuntime, get_are_runtime, reset_are_runtime


def test_are_runtime_singleton():
    reset_are_runtime()
    rt1 = get_are_runtime()
    rt2 = get_are_runtime()
    assert rt1 is rt2


def test_are_runtime_mode_initialization():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    assert rt.current_mode == ARERuntimeMode.CONTROLLED
    assert rt.is_active is False


def test_are_runtime_mode_active_blocked_by_pydantic():
    with pytest.raises(ValidationError):
        AppSettings(ARE_RUNTIME_MODE="ACTIVE")


def test_are_runtime_mode_active_blocked_by_runtime():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    with pytest.raises(PermissionError, match="strictly prohibited"):
        rt.set_mode(ARERuntimeMode.ACTIVE)


def test_are_runtime_mode_transitions():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    rt.set_mode(ARERuntimeMode.SHADOW)
    assert rt.current_mode == ARERuntimeMode.SHADOW

    rt.set_mode(ARERuntimeMode.DISABLED)
    assert rt.current_mode == ARERuntimeMode.DISABLED

    rt.set_mode(ARERuntimeMode.CONTROLLED)
    assert rt.current_mode == ARERuntimeMode.CONTROLLED
