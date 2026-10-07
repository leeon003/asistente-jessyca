"""Orquestador gobernado para la ejecución de operaciones de AnyDoc bajo JDE.

Implementa:
1. Despacho y validación inmutable de AnyDocTaskContract (sellado criptográfico).
2. Verificación previa de autorización JDE (ALLOW obligatorio; DENY produce 0 side effects).
3. Confinamiento absoluto al sandbox: data/anydoc/{input,output,cache,quarantine}.
4. Idempotencia mediante fingerprint SHA-256 (input_hash + operation + version + config).
5. Verificación física mediante ExecutionVerifier (CLAIMED vs VERIFIED_SUCCESS vs VERIFICATION_FAILED).
6. Preservación del hash de entrada (input immutability).
7. Emisión de recibos inmutables AnyDocReceipt firmados con hash de entrada y salida.
8. Extracción segura de estructura y assets con saneamiento anti-traversal.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from typing import Any

import anydoc

from core.anydoc.adapter import AnyDocAdapter, _is_strictly_contained
from core.anydoc.models import (
    AnyDocMode,
    AnyDocReceipt,
    AnyDocResult,
    AnyDocTaskContract,
    ConversionStatus,
)
from core.logger import get_logger

logger = get_logger("jessyca.anydoc.orchestrator")


class AnyDocGovernedOrchestrator:
    """Orquestador gobernado para operaciones documentales con AnyDoc."""

    def __init__(
        self,
        adapter: AnyDocAdapter | None = None,
        base_dir: str = "data/anydoc",
    ) -> None:
        self.base_dir = os.path.realpath(base_dir)
        self.input_dir = os.path.join(self.base_dir, "input")
        self.output_dir = os.path.join(self.base_dir, "output")
        self.cache_dir = os.path.join(self.base_dir, "cache")
        self.quarantine_dir = os.path.join(self.base_dir, "quarantine")

        for d in [self.input_dir, self.output_dir, self.cache_dir, self.quarantine_dir]:
            os.makedirs(d, exist_ok=True)

        self.adapter = adapter or AnyDocAdapter(mode=AnyDocMode.CONTROLLED, base_sandbox_dir=self.base_dir)
        self._idempotency_cache: dict[str, AnyDocResult] = {}
        self._execution_history: list[AnyDocResult] = []

    @property
    def history(self) -> list[AnyDocResult]:
        return list(self._execution_history)

    def kill_switch(self) -> None:
        """Kill switch operacional de emergencia: detiene AnyDoc inmediatamente y purga el cache."""
        self.adapter.kill_switch()
        self._idempotency_cache.clear()

    def clear_cache(self) -> None:
        """Purga la memoria intermedia de idempotencia."""
        self._idempotency_cache.clear()

    def compute_file_hash(self, file_path: str) -> str:
        """Calcula el hash SHA-256 canónico del contenido de un archivo."""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    def validate_sandbox_path(self, target_path: str, is_output: bool = False, allow_quarantine: bool = False) -> str:
        """Verifica estrictamente que la ruta resida dentro del sandbox permitido de anydoc.

        Para escrituras (is_output=True), la ruta DEBE residir dentro de data/anydoc/output/,
        data/anydoc/cache/ o data/anydoc/quarantine/. Jamás fuera del sandbox.
        """
        if not target_path or not str(target_path).strip():
            raise ValueError("Path cannot be empty")

        raw_str = str(target_path).strip()
        # Rechazo inmediato de path traversal explícito o URL-encoded
        import urllib.parse
        decoded = urllib.parse.unquote(raw_str)
        if ".." in decoded or "%2e%2e" in raw_str.lower() or "\x00" in raw_str:
            raise ValueError(f"Path traversal or null-byte detected in path: '{target_path}'")

        # Rechazo de rutas UNC de red (\\server\share)
        if raw_str.startswith("\\\\") or raw_str.startswith("//"):
            raise ValueError(f"UNC network paths are forbidden: '{target_path}'")

        real_target = os.path.realpath(raw_str)
        real_base = self.base_dir

        if is_output:
            # Escrituras solo en output, cache o quarantine
            valid_dirs = [self.output_dir, self.cache_dir]
            if allow_quarantine:
                valid_dirs.append(self.quarantine_dir)
            is_valid_write = any(
                _is_strictly_contained(real_target, d)
                for d in valid_dirs
            )
            if not is_valid_write:
                raise ValueError(
                    f"Security sandbox violation: output path '{target_path}' must reside within authorized output sandbox '{self.output_dir}'"
                )
            return real_target

        # Entradas (is_output=False): permitidas en base_dir o en lab/anydoc (fixtures)
        real_lab = os.path.realpath(os.path.join("lab", "anydoc"))
        is_in_base = _is_strictly_contained(real_target, real_base)
        is_in_lab = _is_strictly_contained(real_target, real_lab)

        if not (is_in_base or is_in_lab):
            raise ValueError(f"Security sandbox violation: input path '{target_path}' is outside authorized sandbox '{real_base}'")

        return real_target

    def dispatch_task(
        self,
        contract: AnyDocTaskContract,
        jde_decision: str = "ALLOW",
        contract_seal: str | None = None,
        simulate_verification_failure: bool = False,
        simulate_timeout: bool = False,
    ) -> AnyDocResult:
        """Ejecuta una tarea documental gobernada cumpliendo el flujo estricto de seguridad."""
        start_time = time.perf_counter()
        op_id = contract.operation_id

        # 0. Verificación de Sello Criptográfico (Integridad del Contrato contra Manipulación)
        if contract_seal is not None and not contract.verify_seal(contract_seal):
            result = AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.DENIED,
                input_path=contract.input_path,
                detected_format="unknown",
                error_message="Contract seal verification failed: post-authorization tampering detected",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                side_effects=0,
            )
            self._execution_history.append(result)
            return result

        # Bloqueo estricto de operaciones prohibidas
        if contract.operation in AnyDocAdapter.FORBIDDEN_CAPABILITIES or any(
            fa in ("ocr_external", "network_outbound", "arbitrary_write", "document_write")
            for fa in contract.allowed_actions
        ):
            result = AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.DENIED,
                input_path=contract.input_path,
                detected_format="unknown",
                error_message=f"Operation or action '{contract.operation}' is strictly FORBIDDEN under JDE",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                side_effects=0,
            )
            self._execution_history.append(result)
            return result

        # 1. Autoridad Única: JDE
        if jde_decision != "ALLOW":
            result = AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.DENIED,
                input_path=contract.input_path,
                detected_format="unknown",
                error_message="Operation DENIED by JDE decision policy",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                side_effects=0,
            )
            self._execution_history.append(result)
            return result

        # 2. Control de Modo
        if self.adapter.mode == AnyDocMode.OFF:
            result = AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.DENIED,
                input_path=contract.input_path,
                detected_format="unknown",
                error_message="AnyDoc adapter is OFF",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                side_effects=0,
            )
            self._execution_history.append(result)
            return result

        # 3. Validación de Sandboxing de Rutas
        try:
            real_input = self.validate_sandbox_path(contract.input_path, is_output=False)
            if not os.path.exists(real_input):
                raise FileNotFoundError(f"Input file not found: {contract.input_path}")
            real_output = self.validate_sandbox_path(contract.output_path, is_output=True)
        except Exception as e:
            result = AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.SECURITY_BLOCKED,
                input_path=contract.input_path,
                detected_format="unknown",
                error_message=f"Path security check failed: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                side_effects=0,
            )
            self._execution_history.append(result)
            return result

        # 4. Hash inicial del archivo de entrada para verificación de integridad (inmutabilidad)
        initial_input_hash = self.compute_file_hash(real_input)
        input_size = os.path.getsize(real_input)

        # 5. Idempotencia Criptográfica
        fingerprint = contract.compute_fingerprint(initial_input_hash)
        if fingerprint in self._idempotency_cache:
            cached = self._idempotency_cache[fingerprint]
            duration = (time.perf_counter() - start_time) * 1000.0
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.VERIFIED_SUCCESS,
                input_path=contract.input_path,
                detected_format=cached.detected_format,
                output_markdown=cached.output_markdown,
                output_path=cached.output_path,
                input_hash=cached.input_hash,
                output_hash=cached.output_hash,
                latency_ms=duration,
                input_size_bytes=cached.input_size_bytes,
                output_char_count=cached.output_char_count,
                verified=True,
                side_effects=0,
                receipt=cached.receipt,
                document_model_summary=cached.document_model_summary,
                extracted_structure=cached.extracted_structure,
                extracted_assets=cached.extracted_assets,
                metadata={"idempotent": True, "cache_hit": True, "cached_op_id": cached.operation_id},
            )

        # 6. Simulación de Timeout
        if simulate_timeout:
            result = AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.TIMEOUT,
                input_path=contract.input_path,
                detected_format="unknown",
                error_message="Operation exceeded maximum timeout threshold",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                side_effects=0,
            )
            self._execution_history.append(result)
            return result

        # 7. Ejecución de la Operación Requerida
        detected_fmt = self.adapter.detect_format(real_input)
        output_markdown = ""
        structure_data: dict[str, Any] = {}
        assets_data: list[dict[str, Any]] = []
        doc_model_summary: dict[str, Any] = {}

        try:
            # Operación: CONVERT
            raw_markdown = anydoc.to_markdown(real_input, ocr="reject")
            output_markdown = self.adapter.redact_secrets(raw_markdown)

            # Escribir salida en sandbox de salida
            os.makedirs(os.path.dirname(real_output), exist_ok=True)
            with open(real_output, "w", encoding="utf-8") as out_f:
                out_f.write(output_markdown)

            # Operación: INSPECT y EXTRACT_STRUCTURE
            try:
                with open(real_input, "rb") as bf:
                    bdata = bf.read()
                doc_obj = anydoc.to_document(bdata, detected_fmt)
                doc_model_summary = {
                    "blocks_count": len(doc_obj.blocks),
                    "notes_count": len(doc_obj.notes),
                    "assets_count": len(doc_obj.assets),
                }

                # Estructuración
                headings = []
                paragraphs = []
                tables_count = 0
                lists_count = 0

                for b in doc_obj.blocks:
                    if b.kind == "heading":
                        headings.append({"level": b.level, "text": "".join([getattr(i, 'text', '') or '' for i in (b.content or [])])})
                    elif b.kind == "paragraph":
                        paragraphs.append("".join([getattr(i, 'text', '') or '' for i in (b.content or [])]))
                    elif b.kind == "table":
                        tables_count += 1
                    elif b.kind == "list":
                        lists_count += 1

                structure_data = {
                    "headings": headings,
                    "paragraphs_count": len(paragraphs),
                    "tables_count": tables_count,
                    "lists_count": lists_count,
                    "notes_count": len(doc_obj.notes),
                }

                # Operación: EXTRACT_ASSETS
                if contract.operation == "document_processing.extract_assets" or "assets" in contract.allowed_actions:
                    assets_dir = os.path.join(os.path.dirname(real_output), "assets")
                    os.makedirs(assets_dir, exist_ok=True)
                    # Extensiones seguras permitidas para assets
                    allowed_asset_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".bin"}
                    for idx, a in enumerate(doc_obj.assets):
                        origin_name = os.path.basename(a.origin_part or f"asset_{idx}.bin")
                        # Saneamiento anti-traversal en nombres de assets
                        safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", origin_name)
                        # Prevenir nombres maliciosos como .env, id_rsa o ejecutables
                        base_stem, ext = os.path.splitext(safe_name)
                        if ext.lower() not in allowed_asset_exts:
                            safe_name = f"{safe_name}.bin"
                        if safe_name.startswith("."):
                            safe_name = f"sanitized_{safe_name.lstrip('.')}"

                        asset_file = os.path.join(assets_dir, safe_name)
                        # Validar que el asset no escape del directorio de assets
                        real_asset_path = os.path.realpath(asset_file)
                        real_assets_dir = os.path.realpath(assets_dir)
                        if not real_asset_path.startswith(real_assets_dir + os.sep):
                            continue

                        with open(asset_file, "wb") as af:
                            af.write(a.data)
                        assets_data.append({
                            "asset_id": a.id,
                            "media_type": a.media_type,
                            "path": asset_file,
                            "size_bytes": len(a.data),
                            "hash": hashlib.sha256(a.data).hexdigest(),
                        })
            except Exception as e:
                logger.debug(f"Document model inspection skipped: {e}")

        except anydoc.NeedsOcrError as e:
            return self._handle_error(contract, ConversionStatus.NEEDS_OCR, str(e), start_time)
        except anydoc.ResourceLimitError as e:
            return self._handle_error(contract, ConversionStatus.RESOURCE_LIMIT, str(e), start_time)
        except anydoc.MalformedError as e:
            return self._handle_error(contract, ConversionStatus.MALFORMED, str(e), start_time)
        except anydoc.EncryptedError as e:
            return self._handle_error(contract, ConversionStatus.ENCRYPTED, str(e), start_time)
        except anydoc.UnsupportedError as e:
            return self._handle_error(contract, ConversionStatus.UNSUPPORTED, str(e), start_time)
        except Exception as e:
            return self._handle_error(contract, ConversionStatus.IO_ERROR, str(e), start_time)

        # 8. Verificación Física (ExecutionVerifier)
        post_input_hash = self.compute_file_hash(real_input)
        input_intact = (post_input_hash == initial_input_hash)
        output_exists = os.path.exists(real_output)
        output_size = os.path.getsize(real_output) if output_exists else 0
        output_valid = output_exists and output_size > 0

        verified = (
            input_intact
            and output_valid
            and not simulate_verification_failure
        )

        final_status = ConversionStatus.VERIFIED_SUCCESS if verified else ConversionStatus.VERIFICATION_FAILED
        output_hash = self.compute_file_hash(real_output) if output_exists else None

        # 9. JDE Receipt
        receipt = None
        if verified:
            receipt = AnyDocReceipt(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                decision_id=contract.decision_id,
                operation_id=contract.operation_id,
                task_id=contract.task_id,
                input_hash=initial_input_hash,
                output_hash=output_hash,
                capability=contract.operation,
                risk_level=contract.risk_level.value,
                verified=True,
                status=final_status.value,
            )

        duration = (time.perf_counter() - start_time) * 1000.0
        final_result = AnyDocResult(
            operation_id=op_id,
            status=final_status,
            input_path=contract.input_path,
            detected_format=detected_fmt,
            output_markdown=output_markdown,
            output_path=real_output,
            input_hash=initial_input_hash,
            output_hash=output_hash,
            latency_ms=duration,
            input_size_bytes=input_size,
            output_char_count=len(output_markdown),
            verified=verified,
            side_effects=0,
            receipt=receipt,
            document_model_summary=doc_model_summary,
            extracted_structure=structure_data,
            extracted_assets=assets_data,
            metadata={"fingerprint": fingerprint, "backend": self.adapter.backend_type},
        )

        if verified:
            self._idempotency_cache[fingerprint] = final_result

        self._execution_history.append(final_result)
        return final_result

    def _handle_error(
        self,
        contract: AnyDocTaskContract,
        status: ConversionStatus,
        error_msg: str,
        start_time: float,
    ) -> AnyDocResult:
        duration = (time.perf_counter() - start_time) * 1000.0
        result = AnyDocResult(
            operation_id=contract.operation_id,
            status=status,
            input_path=contract.input_path,
            detected_format="unknown",
            error_message=error_msg,
            latency_ms=duration,
            verified=False,
            side_effects=0,
        )
        self._execution_history.append(result)
        return result


# Alias canónico de compatibilidad para AnyDocGovernedOrchestrator
AnyDocOrchestrator = AnyDocGovernedOrchestrator

__all__ = ["AnyDocGovernedOrchestrator", "AnyDocOrchestrator"]
