"""Pruebas del modelo inmutable SanitizedCommandOutput (Subetapa 07.5)."""

from __future__ import annotations

import pytest

from core.command_output import SanitizedCommandOutput


def test_sanitized_command_output_immutability() -> None:
    output = SanitizedCommandOutput(
        stdout="clean output",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_original_size=12,
        stderr_original_size=0,
        redactions_count=1,
        total_output_size=12,
    )

    assert output.stdout == "clean output"
    assert output.redactions_count == 1

    with pytest.raises(AttributeError):
        output.stdout = "modified"  # type: ignore

    d = output.to_dict()
    assert d["stdout"] == "clean output"
    assert d["is_sanitized"] is True
