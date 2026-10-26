"""Isolation tests for the optional JESSYCA/OpenHands brain provider."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.cognitive_brain.openhands_provider import (
    DevelopmentTask,
    OpenHandsBrainProvider,
)


class TestOpenHandsBrainProvider(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.calls = []
        self.provider = OpenHandsBrainProvider(
            enabled=True,
            sandbox_root=self.root,
            runner=lambda text, workspace: self.calls.append((text, workspace)) or "ok",
            risk_engine=SimpleNamespace(evaluate_risk=lambda request: SimpleNamespace(risk_level="WARNING")),
            permission_manager=SimpleNamespace(evaluate_permission=lambda request: SimpleNamespace(is_allowed=True)),
        )

    def test_default_disabled(self):
        response = OpenHandsBrainProvider().run(
            DevelopmentTask("test", self.project, approved=True)
        )
        self.assertFalse(response.success)

    def test_requires_approval(self):
        response = self.provider.run(DevelopmentTask("test", self.project))
        self.assertFalse(response.success)
        self.assertEqual(self.calls, [])

    def test_blocks_outside_workspace(self):
        response = self.provider.run(
            DevelopmentTask("test", self.root.parent, approved=True)
        )
        self.assertFalse(response.success)
        self.assertEqual(self.calls, [])

    def test_blocks_root_directory(self):
        response = self.provider.run(
            DevelopmentTask("test", self.root, approved=True)
        )
        self.assertFalse(response.success)

    def test_blocks_missing_directory(self):
        response = self.provider.run(
            DevelopmentTask("test", self.root / "missing", approved=True)
        )
        self.assertFalse(response.success)

    def test_does_not_run_without_runner(self):
        provider = OpenHandsBrainProvider(
            enabled=True, sandbox_root=self.root
        )
        response = provider.run(
            DevelopmentTask("test", self.project, approved=True)
        )
        self.assertFalse(response.success)

    def test_approved_task_runs_once(self):
        response = self.provider.run(
            DevelopmentTask("create test", self.project, approved=True)
        )
        self.assertTrue(response.success)
        self.assertEqual(self.calls, [("create test", self.project.resolve())])

    def test_runner_exception_fails_closed(self):
        provider = OpenHandsBrainProvider(
            enabled=True,
            sandbox_root=self.root,
            runner=lambda *args: 1 / 0,
            risk_engine=SimpleNamespace(evaluate_risk=lambda request: SimpleNamespace(risk_level="WARNING")),
        )
        response = provider.run(
            DevelopmentTask("test", self.project, approved=True)
        )
        self.assertFalse(response.success)

    def test_empty_instruction_rejected(self):
        response = self.provider.run(
            DevelopmentTask(" ", self.project, approved=True)
        )
        self.assertFalse(response.success)
        self.assertEqual(self.calls, [])

    def test_missing_risk_engine_fails_closed(self):
        provider = OpenHandsBrainProvider(
            enabled=True, sandbox_root=self.root,
            runner=lambda *args: self.fail("runner invoked without risk check"),
        )
        self.assertFalse(provider.run(DevelopmentTask("test", self.project, approved=True)).success)

    def test_critical_risk_blocks_execution(self):
        self.provider.risk_engine = SimpleNamespace(
            evaluate_risk=lambda request: SimpleNamespace(risk_level="CRITICAL")
        )
        self.assertFalse(self.provider.run(DevelopmentTask("test", self.project, approved=True)).success)
        self.assertEqual(self.calls, [])

    def test_risk_engine_error_blocks_execution(self):
        def fail(request):
            raise RuntimeError("error")
        self.provider.risk_engine = SimpleNamespace(evaluate_risk=fail)
        self.assertFalse(self.provider.run(DevelopmentTask("test", self.project, approved=True)).success)
        self.assertEqual(self.calls, [])

    def test_risk_engine_gets_typed_request(self):
        from core.security_architecture import SecurityRequest
        def assess(request):
            self.assertIsInstance(request, SecurityRequest)
            self.assertEqual(request.action, "write")
            return SimpleNamespace(risk_level="WARNING")
        self.provider.risk_engine = SimpleNamespace(evaluate_risk=assess)
        self.assertTrue(self.provider.run(DevelopmentTask("test", self.project, approved=True)).success)

    def test_permission_denial_blocks_execution(self):
        self.provider.permission_manager = SimpleNamespace(
            evaluate_permission=lambda request: SimpleNamespace(is_allowed=False)
        )
        self.assertFalse(self.provider.run(DevelopmentTask("test", self.project, approved=True)).success)
        self.assertEqual(self.calls, [])

    def test_permission_manager_receives_request(self):
        from core.permission_manager import PermissionRequest
        def check(request):
            self.assertIsInstance(request, PermissionRequest)
            return SimpleNamespace(is_allowed=True)
        self.provider.permission_manager = SimpleNamespace(evaluate_permission=check)
        self.assertTrue(self.provider.run(DevelopmentTask("test", self.project, approved=True)).success)

    def test_missing_permission_manager_blocks_execution(self):
        self.provider.permission_manager = None
        self.assertFalse(self.provider.run(DevelopmentTask("test", self.project, approved=True)).success)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
