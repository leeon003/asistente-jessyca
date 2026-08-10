"""Pruebas dedicadas para DocumentGenerationBridge, PathSecurityManager sandbox integration y FakeDocumentGenerator (Subetapa 11.4)."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from core.document_bridge import (
    DocumentFormat,
    DocumentGenerationBridge,
    DocumentGenerationRequest,
    DocumentSizeExceededError,
    DocumentTraversalError,
    FakeDocumentGenerator,
    NativeDocumentGenerator,
)
from tools.filesystem.path_security import PathSecurityManager


def test_document_generation_valid_path(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    gen = FakeDocumentGenerator()
    bridge = DocumentGenerationBridge(generator=gen, path_security=path_sec)

    req = DocumentGenerationRequest(
        file_path="reports/summary.md",
        title="Informe Mensual",
        content="Contenido del informe sintético.",
        format=DocumentFormat.MARKDOWN,
    )

    res = bridge.generate_document(req)
    assert res is not None
    assert res.bytes_written > 0
    assert os.path.exists(res.canonical_path)
    assert str(tmp_path.resolve()) in res.canonical_path


def test_document_generation_sandbox_path(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    gen = NativeDocumentGenerator()
    bridge = DocumentGenerationBridge(generator=gen, path_security=path_sec)

    req = DocumentGenerationRequest(
        file_path="notes.txt",
        title="Notas",
        content="Texto plano de notas.",
        format=DocumentFormat.TXT,
    )

    res = bridge.generate_document(req)
    assert Path(res.canonical_path).is_relative_to(tmp_path.resolve())


def test_document_generation_traversal_rejection(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    bridge = DocumentGenerationBridge(path_security=path_sec)

    # Intento de Path Traversal para escapar del sandbox
    req = DocumentGenerationRequest(
        file_path="../escape_sandbox.txt",
        title="Ataque",
        content="Intento de escritura fuera del sandbox",
        format=DocumentFormat.TXT,
    )

    with pytest.raises(DocumentTraversalError):
        bridge.generate_document(req)


def test_document_generation_oversized_output(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    bridge = DocumentGenerationBridge(path_security=path_sec)

    # Contenido de 11 MB (supera el límite de 10 MB)
    large_content = "X" * (11 * 1024 * 1024)
    req = DocumentGenerationRequest(
        file_path="large_doc.txt",
        title="Documento Gigante",
        content=large_content,
        format=DocumentFormat.TXT,
    )

    with pytest.raises(DocumentSizeExceededError):
        bridge.generate_document(req)


def test_document_generation_pipeline_enforcement(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    gen = FakeDocumentGenerator()
    bridge = DocumentGenerationBridge(generator=gen, path_security=path_sec)

    req = DocumentGenerationRequest(
        file_path="authorized.json",
        title="Config",
        content="{}",
        format=DocumentFormat.JSON,
    )

    res = bridge.generate_document(req, request_id="req-pipeline-doc")
    assert res.format == DocumentFormat.JSON
    assert len(res.checksum_sha256) == 64


def test_document_generation_audit_metadata(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    gen = FakeDocumentGenerator()
    bridge = DocumentGenerationBridge(generator=gen, path_security=path_sec)

    req = DocumentGenerationRequest(
        file_path="privacy_test.md",
        title="Título Privado",
        content="INFORMACION_ULTRA_SECRETA_SIN_AUDIT",
        format=DocumentFormat.MARKDOWN,
    )

    res = bridge.generate_document(req)
    assert res.checksum_sha256 is not None


def test_document_generation_regression(tmp_path: Path) -> None:
    path_sec = PathSecurityManager(sandbox_root=tmp_path)
    gen = NativeDocumentGenerator()
    bridge = DocumentGenerationBridge(generator=gen, path_security=path_sec)

    req_json = DocumentGenerationRequest(
        file_path="data.json",
        title="Datos",
        content="hello world",
        format=DocumentFormat.JSON,
    )

    res = bridge.generate_document(req_json)
    with open(res.canonical_path, "r", encoding="utf-8") as f:
        data = f.read()
    assert '"title": "Datos"' in data
    assert '"body": "hello world"' in data
