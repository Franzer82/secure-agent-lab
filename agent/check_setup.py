import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version

from dotenv import load_dotenv

# Dasselbe Modell, das bei InsightScan funktioniert hat. Falls Google die
# Bezeichnung irgendwann ändert, muss sie nur hier an einer Stelle angepasst
# werden.
GEMINI_MODEL = "gemini-3.8-flash"

# Bei Serverfehlern auf Google-Seite (5xx) wiederholen wir kurz, statt sofort
# aufzugeben - solche Fehler sind meist vorübergehend.
MAX_ATTEMPTS = 3
PAUSE_SECONDS = 5


def package_version(name: str) -> str:
    """Liest die installierte Version eines Pakets aus. Wir protokollieren
    die Versionen, damit das Projekt später reproduzierbar ist - bei einem
    Sicherheitsprojekt gehört 'welche Version lief genau?' zur Dokumentation."""
    try:
        return version(name)
    except PackageNotFoundError:
        return "nicht installiert"


def check_mcp_import() -> bool:
    """Prüft, ob das MCP-SDK installiert ist und die Klassen verfügbar sind,
    die wir später für Server und Client brauchen. In MCP 2.x heißt die
    Server-Klasse MCPServer (in 1.x hieß sie FastMCP)."""
    try:
        from mcp import ClientSession, StdioServerParameters  # noqa: F401
        from mcp.client.stdio import stdio_client  # noqa: F401
        from mcp.server.mcpserver import MCPServer  # noqa: F401
    except ImportError as error:
        print(f"MCP-SDK: FEHLER beim Import ({error})")
        return False

    print(f"MCP-SDK: OK (Version {package_version('mcp')}, Server- und Client-Klassen importierbar)")
    return True


def check_gemini_access() -> bool:
    """Schickt eine minimale Anfrage an Gemini, um zu bestätigen, dass der
    Schlüssel gültig ist und das Modell erreichbar. Der Schlüssel selbst wird
    NIE ausgegeben, nicht einmal teilweise - Zugangsdaten gehören weder in
    die Konsole noch in Logdateien. Von Fehlern zeigen wir nur Statuscode und
    Status-Text, nicht die komplette Meldung (die könnte Teile der Anfrage
    enthalten)."""
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("Gemini: FEHLER - GEMINI_API_KEY nicht gefunden (.env prüfen)")
        return False

    from google import genai
    from google.genai import errors

    client = genai.Client(api_key=api_key)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents="Antworte nur mit dem Wort: bereit",
            )
        except errors.ServerError as error:
            # 5xx: Der Fehler liegt auf Googles Seite, meist vorübergehend.
            code = getattr(error, "code", "?")
            status = getattr(error, "status", "?")
            print(f"Gemini: Serverfehler bei Versuch {attempt}/{MAX_ATTEMPTS} (Code {code}, {status})")
            if attempt < MAX_ATTEMPTS:
                time.sleep(PAUSE_SECONDS)
                continue
            print("Gemini: Google antwortet dauerhaft mit Serverfehlern - später erneut versuchen.")
            return False
        except errors.APIError as error:
            # 4xx: Der Fehler liegt bei uns (Schlüssel, Modellname, Limit).
            code = getattr(error, "code", "?")
            status = getattr(error, "status", "?")
            print(f"Gemini: FEHLER (Code {code}, {status})")
            if code in (401, 403):
                print("  Hinweis: Schlüssel ungültig oder ohne Berechtigung (.env prüfen).")
            elif code == 404:
                print("  Hinweis: Modellbezeichnung unbekannt (GEMINI_MODEL anpassen).")
            elif code == 429:
                print("  Hinweis: Anfragelimit der kostenlosen Stufe erreicht - kurz warten.")
            return False
        except Exception as error:
            print(f"Gemini: FEHLER bei der Anfrage ({type(error).__name__})")
            return False

        answer = (response.text or "").strip()
        print(f"Gemini: OK (Version google-genai {package_version('google-genai')}, Antwort: {answer})")
        return True

    return False


if __name__ == "__main__":
    mcp_ok = check_mcp_import()
    gemini_ok = check_gemini_access()

    if mcp_ok and gemini_ok:
        print("\nAlles bereit für Phase 2.")
    else:
        print("\nBitte die Fehler oben beheben, bevor wir weitermachen.")
        sys.exit(1)