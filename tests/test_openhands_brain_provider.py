"""Isolation tests for the optional JESSYCA/OpenHands brain provider."""
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
