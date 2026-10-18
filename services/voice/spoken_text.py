"""Prepare displayed answers for speech without changing the written response."""

import re


def prepare_spoken_text(text: str) -> str:
    """Keep prose and link labels; never read hidden reasoning or raw markup."""
    text = re.sub(r"<think\b[^>]*>.*?(?:</think>|$)", "", text, flags=re.S | re.I)
    text = re.sub(r"```[^\n]*\n.*?(?:```|$)", " El código está disponible en la conversación. ", text, flags=re.S)
    text = re.sub(r"!?\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", text)
    text = re.sub(r"https?://[^\s<>]+", "", text)
    text = re.sub(r"\[(?:\d+)(?:\s*[,–-]\s*\d+)*\]", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|>\s*)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()
