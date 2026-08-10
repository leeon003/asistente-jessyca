"""Pruebas de los modelos inmutables de Servicios (Subetapa 06.5)."""

from __future__ import annotations

import pytest

from tools.services.models import (
    WindowsServiceInfo,
    WindowsServiceQueryResult,
    WindowsServiceStatus,
)


def test_service_info_immutability_and_dict() -> None:
    info = WindowsServiceInfo(
        service_name="wuauserv",
        display_name="Windows Update",
        status="running",
        start_type="automatic",
        service_type="share_process",
        dependencies=("rpcss",),
        description="Windows Update service",
        binpath="C:\\Windows\\System32\\svchost.exe",
    )

    assert info.service_name == "wuauserv"
    assert info.dependencies == ("rpcss",)

    with pytest.raises(AttributeError):
        info.status = "stopped"  # type: ignore

    d = info.to_dict()
    assert d["service_name"] == "wuauserv"
    assert d["dependencies"] == ["rpcss"]


def test_service_status_and_query_result() -> None:
    st = WindowsServiceStatus(status_str="running", pid=4321)
    assert st.status_str == "running"
    assert st.to_dict()["pid"] == 4321

    info = WindowsServiceInfo(
        service_name="Spooler",
        display_name="Print Spooler",
        status="running",
        start_type="automatic",
        service_type="own_process",
    )

    res = WindowsServiceQueryResult(count=1, truncated=False, services=(info,))
    assert res.count == 1
    assert res.to_dict()["services"][0]["service_name"] == "Spooler"
