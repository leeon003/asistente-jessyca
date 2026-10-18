"""Deterministic YouTube commands, including spoken corrections in Spanish."""
import re


def resolve_explicit_youtube(text: str):
    prefix = r"^\s*¿?(?:jess(?:y|i)ca[,\s]+)?(?:(?:no,\s*)?(?:te\s+ped[ií]|te\s+he\s+pedido|quiero|necesito|puedes|podr[ií]as)\s+(?:que\s+)?)?"
    play = r"(?:reproduce|reproduzcas|reproduzca|reproducir|pon|pongas|poner)"
    opening = r"(?:abre|abrir|abra|abras|habras|habrás)"
    if re.search(r"\bno\s+(?:quiero|abras|abra|abre|reproduzcas|reproduce|pongas|pongas)\b", text, re.I):
        return None
    patterns = [prefix + opening + r"\s+(?:el\s+)?youtube\s+y\s+" + play + r"\s+(.+?)\s*$",
                prefix + play + r"\s+(.+?)\s+en\s+youtube\s*[.?!]*$"]
    for pattern in patterns:
        match = re.match(pattern, text, re.I)
        if match:
            query = match.group(1).strip(' \t\n.?!"“”')
            if query:
                return 'youtube_play', {'query': query, 'action': 'play'}, False
    match = re.match(prefix + r"(?:busca|buscar|busques)\s+(.+?)\s+en\s+youtube\s*[.?!]*$", text, re.I)
    if match:
        return 'youtube_search', {'query': match.group(1).strip(' .?!'), 'motor': 'youtube'}, False
    if re.match(prefix + opening + r"\s+(?:el\s+)?youtube\s*[.?!]*$", text, re.I):
        return 'open_browser', {'url': 'https://www.youtube.com', 'site': 'YouTube'}, False
    return None
