"""OpenHands SDK real DockerWorkspace smoke check, no LLM or host workspace mount.
Requires Docker daemon and openhands-workspace installed. No API credentials.
"""
from __future__ import annotations
import sys

def main() -> int:
    try:
        from openhands.workspace import DockerWorkspace
    except ImportError as exc:
        print(f"SDK missing: {exc}", file=sys.stderr)
        return 2
    try:
        with DockerWorkspace(server_image="ghcr.io/openhands/agent-server:latest-python") as workspace:
            result = workspace.execute_command("python -c 'print(12345)'")
            print(f"sandbox exit_code={result.exit_code} stdout={result.stdout!r}")
            assert result.exit_code == 0, "Sandbox command failed"
            assert "12345" in result.stdout, "Unexpected sandbox output"
        return 0
    except Exception as exc:
        print(f"OpenHands sandbox test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
