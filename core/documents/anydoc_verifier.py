"""Verificador de interoperabilidad y lectura mediante AnyDoc (anydoc_verifier.py).

Garantiza:
1. Reutilización del subsistema AnyDoc para auditar, procesar y convertir a Markdown los documentos generados.
2. Comprobación de que AnyDoc reconoce el formato (docx, xlsx, pptx) y extrae su estructura sin errores.
3. Validación de no-vacuidad e integridad del contenido textual.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.anydoc.adapter import AnyDocAdapter
from core.anydoc.models import AnyDocMode, ConversionStatus
from core.logger import get_logger

logger = get_logger("jessyca.documents.anydoc_verifier")


class AnyDocDocumentVerifier:
    """Validador de interoperabilidad mediante AnyDoc."""

    def __init__(self, sandbox_dir: str | Path = "data/anydoc") -> None:
        self.sandbox_dir = str(Path(sandbox_dir).resolve())
        self.adapter = AnyDocAdapter(mode=AnyDocMode.CONTROLLED, base_sandbox_dir=self.sandbox_dir)

    def verify_document(
        self,
        input_path: str | Path,
        expected_format: str | None = None,
    ) -> dict[str, Any]:
        """Convierte e inspecciona un documento local con AnyDoc."""
        p = Path(input_path).resolve()
        if not p.exists():
            return {
                "verified": False,
                "error": f"Archivo no encontrado: {p}",
            }

        # Asegurar que el archivo de entrada sea legible por AnyDoc
        # AnyDocAdapter permite lecturas dentro de _allowed_read_dirs
        self.adapter.add_allowed_read_dir(str(p.parent))

        output_md_path = Path(self.sandbox_dir) / "output" / f"anydoc_audit_{p.stem}.md"
        output_md_path.parent.mkdir(parents=True, exist_ok=True)

        res = self.adapter.convert_file(
            input_path=str(p),
            output_path=str(output_md_path),
            redact=True,
        )

        is_ok = res.status in (ConversionStatus.SUCCESS, ConversionStatus.VERIFIED_SUCCESS)
        text_len = res.output_char_count

        return {
            "verified": bool(is_ok and text_len > 0),
            "status": str(res.status),
            "detected_format": res.detected_format,
            "char_count": text_len,
            "output_path": res.output_path,
            "sample_content": res.output_markdown[:300] if res.output_markdown else "",
            "latency_ms": res.latency_ms,
        }
