"""Incremental text-to-speech with bounded phrases and cooperative interruption.

No provider-specific code: callers retain ownership of security and audio capture.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from core.cancellation import CancellationToken


@dataclass
class SpeechStreamMetrics:
    # A TTS request is not proof that sound reached a physical speaker.
    first_text_ms: float | None = None
    first_tts_request_ms: float | None = None
    total_ms: float = 0.0
    phrases_spoken: int = 0
    interrupted: bool = False


def speak_stream(
    tokens: Iterator[str],
    speak: Callable[[str], bool],
    token: CancellationToken,
    *,
    max_chars: int = 180,
    metrics: SpeechStreamMetrics | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> SpeechStreamMetrics:
    """Speak complete phrases before generation ends; never drain after cancellation.

    A long unpunctuated response is split at whitespace or at max_chars.
    Backpressure is synchronous, so there is no unbounded audio/text queue.
    """
    if max_chars < 16:
        raise ValueError("max_chars must be at least 16")
    result = metrics if metrics is not None else SpeechStreamMetrics()
    started = clock()
    pending = ""

    def emit(phrase: str) -> bool:
        if token.is_cancelled:
            return False
        if result.first_tts_request_ms is None:
            result.first_tts_request_ms = (clock() - started) * 1000
        if not speak(phrase.strip()):
            token.cancel()
            return False
        result.phrases_spoken += 1
        return not token.is_cancelled

    try:
        while not token.is_cancelled:
            try:
                chunk = next(tokens)
            except StopIteration:
                break
            if token.is_cancelled:
                break
            if not chunk:
                continue
            if result.first_text_ms is None:
                result.first_text_ms = (clock() - started) * 1000
            pending += chunk
            while pending.strip() and not token.is_cancelled:
                boundary = re.search(r"[.!?。！？](?=\s|$)|\n", pending)
                cut = boundary.end() if boundary else 0
                if not cut or cut > max_chars:
                    if len(pending) < max_chars:
                        break
                    # Prefer a natural clause break rather than splitting mid-thought.
                    clause = list(re.finditer(r"[,;:](?=\\s)", pending[:max_chars + 1]))
                    cut = clause[-1].end() if clause and clause[-1].end() >= max_chars // 2 else 0
                    if not cut:
                        cut = pending.rfind(" ", 0, max_chars + 1)
                    if cut <= 0:
                        cut = max_chars
                phrase, pending = pending[:cut], pending[cut:]
                if not emit(phrase):
                    break
        if pending.strip() and not token.is_cancelled:
            emit(pending)
        return result
    except BaseException:
        token.cancel()
        raise
    finally:
        result.interrupted = token.is_cancelled
        result.total_ms = (clock() - started) * 1000
        close = getattr(tokens, "close", None)
        if close:
            close()
