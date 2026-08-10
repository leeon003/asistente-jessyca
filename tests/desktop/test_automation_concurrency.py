"""Pruebas de concurrencia multi-hilo y parada de emergencia reactiva (Subetapa 08.4)."""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
    generate_action_fingerprint,
)
from core.emergency_stop import get_emergency_stop_manager
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from tools.desktop.automation_backend import FakeDesktopAutomationBackend
from tools.desktop.automation_service import DesktopAutomationService


def test_concurrent_automation_requests_and_emergency_stop() -> None:
    backend = FakeDesktopAutomationBackend()
    service = DesktopAutomationService(backend=backend)
    em = get_emergency_stop_manager()
    em.deactivate()

    def worker(worker_id: int) -> bool:
        target = DesktopActionTarget(x=10 + worker_id, y=20 + worker_id)
        req = DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=target)
        req_id = f"aut-conc-{worker_id}"

        fp = generate_action_fingerprint("windows.desktop", "click_element", target.to_dict(), {}, req_id)
        evidence = AuthorizationEvidence(
            evidence_id=f"ev-conc-{worker_id}",
            request_id=req_id,
            decision=PermissionDecision.ALLOW,
            policy_rules_evaluated=(),
            user_confirmed=True,
            evaluation_timestamp=datetime.now(UTC),
            risk_level=SecurityLevel.DANGEROUS,
            action_fingerprint=fp,
            is_valid=True,
        )

        try:
            res = service.execute_action(req, evidence, request_id=req_id)
            return res.success
        except Exception:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
