"""Isolated checks; no live OpenHands server or Windows changes required."""
import json
import unittest
from unittest.mock import MagicMock, patch
from integrations.openhands_bridge import OpenHandsBridge, OpenHandsConfig


class BridgeTests(unittest.TestCase):
    def test_defaults_disabled(self):
        with patch("integrations.openhands_bridge.urlopen") as request:
            self.assertFalse(OpenHandsBridge().status()["enabled"])
            request.assert_not_called()

    def test_deny_external_hosts(self):
        for endpoint in (
            "https://example.org", "http://192.168.1.20:8000",
            "file:///etc/passwd", "http://user:pass@localhost:8000",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                OpenHandsConfig(endpoint=endpoint)

    def test_timeout_validation(self):
        for value in (0, -1, 60):
            with self.assertRaises(ValueError):
                OpenHandsConfig(timeout_seconds=value)

    def test_enabled_ping(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps({"openapi": "3.0.0"}).encode()
        response.__enter__.return_value = response
        with patch("integrations.openhands_bridge.urlopen", return_value=response):
            result = OpenHandsBridge(OpenHandsConfig(enabled=True)).status()
        self.assertTrue(result["reachable"])

    def test_offline_fails_closed(self):
        with patch("integrations.openhands_bridge.urlopen", side_effect=OSError("offline")):
            result = OpenHandsBridge(OpenHandsConfig(enabled=True)).status()
        self.assertFalse(result["reachable"])

    def test_wrong_api_not_accepted(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        with patch("integrations.openhands_bridge.urlopen", return_value=response):
            self.assertFalse(OpenHandsBridge(OpenHandsConfig(enabled=True)).status()["reachable"])


if __name__ == "__main__":
    unittest.main()
