import re
from urllib.parse import urlparse

# =============================================================================
# AUSGABEFILTER VERSION 2: Bilder und externe Links werden aus der Antwort
# entfernt, bevor sie den Nutzer erreichen.
#
# Warum: Ein Bild- oder Link-Aufruf ist ein Kanal, über den Daten nach außen
# gelangen können (die Adresse selbst kann Informationen enthalten, und ein
# Chat-Fenster lädt Bilder oft automatisch). Das entfernt die Möglichkeit, statt
# darauf zu hoffen, dass das Modell sie nicht nutzt.
#
# Grenzen (gehören in den Bericht): Der Filter erkennt keine verschleierten
# Adressen (etwa mit Leerzeichen oder "hxxp"), und er kennt nur die hier
# aufgeführten Schreibweisen.
# =============================================================================

COMPANY_DOMAIN = "nordlicht-lab.example"

_IMAGE_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_REF = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")
_IMAGE_HTML = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_REF_DEFINITION = re.compile(r"^([ \t]*\[[^\]]+\]:[ \t]*)(https?://\S+)(.*)$", re.MULTILINE | re.IGNORECASE)
_LINK_MD = re.compile(r"\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_URL = re.compile(r"https?://[^\s)\]>\"']*[^\s)\]>\"'.,;:!?]", re.IGNORECASE)


def _is_internal(url: str) -> bool:
    """Ein Link gilt nur als intern, wenn sein HOSTNAME die Firmendomain oder eine
    ihrer Subdomains ist. Ein reiner Textvergleich würde Tricks wie
    'nordlicht-lab.example.boese.example' oder 'nordlicht-lab.example@boese.example'
    durchlassen. Deshalb wird die Adresse erst zerlegt."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == COMPANY_DOMAIN or host.endswith("." + COMPANY_DOMAIN)


def _replace_link(match: re.Match) -> str:
    label, target = match.group(1), match.group(2)
    if not target.lower().startswith(("http://", "https://")):
        return match.group(0)  # relative Links und mailto bleiben
    if _is_internal(target):
        return match.group(0)
    return f"{label} (Link entfernt)" if label else "[Link entfernt]"


def _replace_reference(match: re.Match) -> str:
    if _is_internal(match.group(2)):
        return match.group(0)
    return ""


def _replace_url(match: re.Match) -> str:
    return match.group(0) if _is_internal(match.group(0)) else "[Link entfernt]"


def filter_output_v2(text: str) -> str:
    # Reihenfolge ist wichtig: Erst Bilder (sie enthalten Adressen), dann
    # Link-Definitionen, dann Markdown-Links, zuletzt freistehende Adressen.
    text = _IMAGE_MD.sub("[Bild entfernt]", text)
    text = _IMAGE_REF.sub("[Bild entfernt]", text)
    text = _IMAGE_HTML.sub("[Bild entfernt]", text)
    text = _REF_DEFINITION.sub(_replace_reference, text)
    text = _LINK_MD.sub(_replace_link, text)
    text = _URL.sub(_replace_url, text)
    return text