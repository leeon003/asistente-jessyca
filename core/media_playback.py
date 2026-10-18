"""Owned FFplay process and independently observed playback progress."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

import psutil

from core.execution.execution_verifier import ExecutionEvidence


class ManagedMediaPlayer:
    """Control only the player created by this instance; never kill unrelated players."""

    def __init__(self):
        self.process = None
        self._log_handle = None
        self.playback_log = None

    def stop(self):
        process = self.process
        if process is not None and process.poll() is None:
            try:
                if os.name == 'nt':
                    import win32gui
                    import win32process
                    def close_owned_window(hwnd, _):
                        if win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid:
                            win32gui.PostMessage(hwnd, 0x0010, 0, 0)
                    win32gui.EnumWindows(close_owned_window, None)
                else:
                    process.stdin.write(b'q')
                    process.stdin.flush()
                process.wait(timeout=0.5)
            except (OSError, ImportError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2)
        if process is not None and process.stdin is not None:
            process.stdin.close()
        if self._log_handle is not None:
            self._log_handle.close()
        self.process = None
        self._log_handle = None

    def launch(self, video_path):
        executable = shutil.which('ffplay')
        if not executable:
            return False, 'FFplay no está instalado o no está en PATH.', None
        path = Path(video_path).resolve(strict=True)
        self.stop()
        log_dir = Path(__file__).resolve().parents[1] / 'logs' / 'media'
        log_dir.mkdir(parents=True, exist_ok=True)
        self.playback_log = log_dir / f'playback_{uuid.uuid4().hex}.log'
        self._log_handle = self.playback_log.open('wb')
        try:
            self.process = subprocess.Popen(
                [executable, '-autoexit', '-stats', '-window_title', f'JESSYCA — {path.name}', '-i', str(path)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log_handle,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            return True, 'PLAYBACK_LAUNCHED', self.process.pid
        except OSError as exc:
            self._log_handle.close()
            self._log_handle = None
            return False, str(exc), None


class MediaPlaybackVerificationStrategy:
    """Match PID + exact input path, then observe the decoder clock advancing."""

    def verify(self, action, target, parameters=None, timeout_seconds=3.0):
        params = parameters or {}
        pid, log_name, file_name = params.get('pid'), params.get('playback_log'), params.get('video_path')
        details = {'pid': pid, 'file_path': file_name, 'scope': 'decoder_clock_advancing'}
        if not pid or not log_name or not file_name:
            return ExecutionEvidence('media_clock', target, False, details)
        deadline = time.monotonic() + timeout_seconds
        first_clock = None
        try:
            process = psutil.Process(pid)
            cmd = process.cmdline()
            expected = Path(file_name).resolve()
            if not process.name().lower().startswith('ffplay') or '-i' not in cmd:
                return ExecutionEvidence('media_clock', target, False, details)
            if Path(cmd[cmd.index('-i') + 1]).resolve() != expected:
                return ExecutionEvidence('media_clock', target, False, details)
            log = Path(log_name)
            while time.monotonic() < deadline:
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                    break
                # Restrict reads to a bounded tail; long-running playback logs can grow.
                with log.open('rb') as stream:
                    stream.seek(max(0, log.stat().st_size - 16384))
                    text = stream.read().decode('utf-8', errors='replace')
                clocks = re.findall(r'(?:^|[\r\n])\s*(\d+\.\d+)\s+(?:A-V|M-V|M-A):', text)
                if clocks:
                    clock = float(clocks[-1])
                    if first_clock is None:
                        first_clock = clock
                    if clock - first_clock >= 0.15:
                        details.update({'clock_start': first_clock, 'clock_end': clock,
                                        'process_create_time': process.create_time()})
                        return ExecutionEvidence('media_clock', target, True, details)
                time.sleep(0.05)
        except (OSError, ValueError, IndexError, psutil.Error) as exc:
            details['error'] = str(exc)
        return ExecutionEvidence('media_clock', target, False, details)
