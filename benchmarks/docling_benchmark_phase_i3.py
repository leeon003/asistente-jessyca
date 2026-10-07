"""Benchmark empírico comparativo entre AnyDoc (Firecrawl) y Docling (Fase I3).

Evalúa sobre el mismo corpus no sensible:
- simple.pdf (PDF digital de dos páginas)
- simple.xlsx (Hoja de cálculo con múltiples tablas)
- simple.csv (Datos tabulares planos)
- scanned.pdf (Documento escaneado que requiere OCR)
- truncated.docx (Documento malformado)

Mide:
- Latencia real en milisegundos (perf_counter)
- Estado de conversión (ConversionStatus)
- Extracción estructurada de tablas y páginas
- Longitud de caracteres exportados
- Comportamiento de aislamiento y seguridad
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core.anydoc import AnyDocAdapter, AnyDocMode, ConversionStatus


def run_benchmark() -> dict:
    fixtures_dir = os.path.realpath(os.path.join("lab", "anydoc", "fixtures"))
    test_files = [
        ("simple.pdf", "PDF Digital"),
        ("simple.xlsx", "Tablas Complejas XLSX"),
        ("simple.csv", "Tabla CSV"),
        ("scanned.pdf", "PDF Escaneado (OCR)"),
        ("truncated.docx", "Archivo Malformado"),
    ]

    adapter_anydoc = AnyDocAdapter(mode=AnyDocMode.LAB, backend="anydoc")
    adapter_docling = AnyDocAdapter(mode=AnyDocMode.LAB, backend="docling")

    results = []

    for filename, description in test_files:
        filepath = os.path.join(fixtures_dir, filename)
        if not os.path.exists(filepath):
            continue

        file_size = os.path.getsize(filepath)

        # 1. AnyDoc Native
        t0 = time.perf_counter()
        res_anydoc = adapter_anydoc.convert_file(filepath)
        lat_anydoc = (time.perf_counter() - t0) * 1000.0

        # 2. Docling Backend
        t0 = time.perf_counter()
        res_docling = adapter_docling.convert_file(filepath)
        lat_docling = (time.perf_counter() - t0) * 1000.0

        entry = {
            "file": filename,
            "description": description,
            "size_bytes": file_size,
            "anydoc_native": {
                "status": res_anydoc.status.value,
                "latency_ms": round(lat_anydoc, 2),
                "output_chars": len(res_anydoc.output_markdown or ""),
                "tables_extracted": res_anydoc.document_model_summary.get("tables_count", 0),
                "error": res_anydoc.error_message,
            },
            "docling_backend": {
                "status": res_docling.status.value,
                "latency_ms": round(lat_docling, 2),
                "output_chars": len(res_docling.output_markdown or ""),
                "tables_extracted": res_docling.extracted_structure.get("tables_count", 0),
                "pages_count": res_docling.extracted_structure.get("pages_count", 0),
                "error": res_docling.error_message,
            },
        }
        results.append(entry)

    adapter_anydoc.close()
    adapter_docling.close()

    output_report = {
        "timestamp": time.time(),
        "benchmark": "AnyDoc vs Docling Comparative Corpus Evaluation (Phase I3)",
        "results": results,
    }

    report_path = Path("reports/docling_phase_i3_benchmark.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(output_report, f, indent=2, ensure_ascii=False)

    print("=== BENCHMARK COMPARATIVO REAL (ANYDOC vs DOCLING) ===")
    for r in results:
        print(f"\nArchivo: {r['file']} ({r['description']}) - {r['size_bytes']} bytes")
        an = r["anydoc_native"]
        dc = r["docling_backend"]
        print(f"  AnyDoc  -> Status: {an['status']:<12} | Latencia: {an['latency_ms']:>8.2f} ms | Chars: {an['output_chars']:>6} | Tablas: {an['tables_extracted']}")
        print(f"  Docling -> Status: {dc['status']:<12} | Latencia: {dc['latency_ms']:>8.2f} ms | Chars: {dc['output_chars']:>6} | Tablas: {dc['tables_extracted']} | Páginas: {dc['pages_count']}")

    return output_report


if __name__ == "__main__":
    run_benchmark()
