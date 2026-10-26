"""Regression tests for natural streaming phrase boundaries."""
import unittest
import importlib.util
import sys
import types
from pathlib import Path

# Load the real streaming module without initializing JESSYCA's entire Windows stack.
class CancellationToken:
    def __init__(self):
        self.is_cancelled = False
    def cancel(self):
        self.is_cancelled = True

core = types.ModuleType("core")
core.__path__ = []
cancellation = types.ModuleType("core.cancellation")
cancellation.CancellationToken = CancellationToken
sys.modules.setdefault("core", core)
sys.modules.setdefault("core.cancellation", cancellation)
source = Path(__file__).resolve().parents[2] / "services" / "voice" / "streaming.py"
spec = importlib.util.spec_from_file_location("_voice_streaming_under_test", source)
streaming = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = streaming
spec.loader.exec_module(streaming)
speak_stream = streaming.speak_stream


class ProsodyTests(unittest.TestCase):
    def test_prefers_clauses_when_a_phrase_is_long(self):
        phrases = []
        text = "Esta es una idea bastante extensa, y aquí viene una explicación todavía más detallada sin punto final"
        speak_stream(iter([text]), lambda phrase: phrases.append(phrase) or True, CancellationToken(), max_chars=58)
        self.assertTrue(phrases[0].endswith(","))
        self.assertEqual(" ".join(" ".join(phrases).split()), " ".join(text.split()))

    def test_short_commas_remain_in_same_sentence(self):
        phrases = []
        speak_stream(iter(["Hola, ¿cómo te va?"]), lambda s: phrases.append(s) or True, CancellationToken())
        self.assertEqual(phrases, ["Hola, ¿cómo te va?"])

    def test_cancel_does_not_speak_next_clause(self):
        phrases = []
        token = CancellationToken()
        def speak(phrase):
            phrases.append(phrase)
            token.cancel()
            return True
        speak_stream(iter(["Una frase bastante extensa, y otra frase bastante extensa que no se debe pronunciar"]), speak, token, max_chars=48)
        self.assertEqual(len(phrases), 1)


if __name__ == "__main__":
    unittest.main()
