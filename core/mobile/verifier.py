"""core/mobile/verifier.py

Verificador Físico de Estado en Primer Plano para Dispositivos Móviles (JDE).
Cumple el contrato de Anti-Falso Éxito de JDE:
1. "Tool execution returned 0" != "App is in foreground".
2. Comprueba mediante inspección real que el package_name está activo en pantalla.
3. Genera evidencia inmutable con hash forense SHA-256.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from core.jde.receipts import JDEEvidence
from core.jde.verification import (
    VerificationContract,
    VerificationOutcome,
    VerificationStatusType,
)
from core.logger import get_logger
from core.mobile.driver import DeviceDisconnectedError, MobilewrightDriver
from core.mobile.models import MobileActionEvidence

logger = get_logger("jessyca.mobile.verifier")


class MobileAppForegroundVerifier:
    """Verificador de primer plano para aplicaciones móviles en JDE."""

    def __init__(self, driver: MobilewrightDriver) -> None:
        self.driver = driver

    def verify(
        self,
        contract: VerificationContract,
        context: dict[str, Any] | None = None,
    ) -> VerificationOutcome:
        """Comprueba físicamente si la aplicación especificada en el contrato está en primer plano."""
        t0 = time.perf_counter()
        ctx = context or {}
        device_id = ctx.get("device_id")
        expected_package = contract.target

        if not device_id:
            return VerificationOutcome.unknown(
                verification_type="mobile_app_foreground",
                target=expected_package,
                reason="No se especificó device_id en el contexto de verificación.",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        timeout = contract.timeout_seconds
        poll_interval = contract.poll_interval_seconds
        deadline = time.perf_counter() + timeout

        last_observed_pkg: str | None = None
        last_observed_act: str | None = None

        while time.perf_counter() < deadline:
            try:
                observed_pkg, observed_act = self.driver.get_foreground_app(device_id=device_id, deadline_seconds=1.0)
                last_observed_pkg = observed_pkg
                last_observed_act = observed_act

                if observed_pkg == expected_package:
                    duration_ms = (time.perf_counter() - t0) * 1000
                    raw_evidence = f"{device_id}:{expected_package}:{observed_act}:{time.time()}"
                    ev_hash = hashlib.sha256(raw_evidence.encode("utf-8")).hexdigest()[:16]

                    evidence_data = MobileActionEvidence(
                        device_id=device_id,
                        action_name=contract.action_name,
                        target_package=expected_package,
                        is_verified=True,
                        observed_foreground_package=observed_pkg,
                        observed_foreground_activity=observed_act,
                        evidence_hash=ev_hash,
                        duration_ms=duration_ms,
                    )

                    jde_ev = JDEEvidence(
                        verification_type="mobile_app_foreground",
                        target=expected_package,
                        is_verified=True,
                        observed_state=evidence_data.model_dump(),
                        details={
                            "device_id": device_id,
                            "evidence_hash": ev_hash,
                            "activity": observed_act,
                        },
                    )

                    logger.info(
                        f"[MOBILE VERIFIER SUCCESS] App '{expected_package}' confirmada en foreground "
                        f"en dispositivo '{device_id}' (Hash: {ev_hash})."
                    )

                    return VerificationOutcome(
                        status=VerificationStatusType.VERIFIED_TRUE,
                        is_verified=True,
                        evidence=jde_ev,
                        reason=f"La aplicación '{expected_package}' quedó físicamente en primer plano.",
                        duration_ms=duration_ms,
                    )
            except DeviceDisconnectedError:
                duration_ms = (time.perf_counter() - t0) * 1000
                return VerificationOutcome.unknown(
                    verification_type="mobile_app_foreground",
                    target=expected_package,
                    reason=f"El dispositivo '{device_id}' se desconectó durante la verificación.",
                    duration_ms=duration_ms,
                )
            except Exception as ex:
                logger.debug(f"[MOBILE VERIFIER POLL] Excepción temporal en sondeo: {ex}")

            time.sleep(poll_interval)

        # Si expiró el tiempo sin observar la aplicación en foreground
        duration_ms = (time.perf_counter() - t0) * 1000
        raw_fail = f"{device_id}:{expected_package}:{last_observed_pkg}:FAIL"
        fail_hash = hashlib.sha256(raw_fail.encode("utf-8")).hexdigest()[:16]

        jde_ev_failed = JDEEvidence(
            verification_type="mobile_app_foreground",
            target=expected_package,
            is_verified=False,
            observed_state={
                "device_id": device_id,
                "expected": expected_package,
                "observed": last_observed_pkg,
                "evidence_hash": fail_hash,
            },
            details={"reason": "App no alcanzó el primer plano antes del timeout."},
        )

        logger.warning(
            f"[MOBILE VERIFIER FAILED] App '{expected_package}' NO quedó en foreground "
            f"(observado: '{last_observed_pkg}', Hash: {fail_hash})."
        )

        return VerificationOutcome(
            status=VerificationStatusType.VERIFIED_FALSE,
            is_verified=False,
            evidence=jde_ev_failed,
            reason=f"La aplicación esperada '{expected_package}' no quedó en primer plano (actual: '{last_observed_pkg}').",
            duration_ms=duration_ms,
        )
