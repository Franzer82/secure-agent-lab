import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version

from lab_settings import GEMINI_MODEL
from usage_budget import DailyBudgetExhausted, record_request

# Bei Serverfehlern auf Google-Seite (5xx) wiederholen wir kurz, statt sofort
# aufzugeben - solche Fehler sind meist vorübergehend.
MAX_ATTEMPTS = 3
PAUSE_SECONDS = 5


def package_version(name: str) -> str:
    """Liest die installierte Version eines Pakets aus. Wir protokollieren
    die Versionen, damit das Projekt später reproduzierbar ist."""
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
    """Schickt EINE minimale Anfrage an Gemini, um zu bestätigen, dass der
    Schlüssel gültig ist und das Modell erreichbar. Der Schlüssel selbst wird
    NIE ausgegeben. Von Fehlern zeigen wir nur Statuscode und Status-Text."""
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("Gemini: FEHLER - GEMINI_API_KEY nicht gefunden (.env prüfen)")
        return False

    from google import genai
    from google.genai import errors

    client = genai.Client(api_key=api_key)
    print(f"Gemini: Modell {GEMINI_MODEL}")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            record_request(GEMINI_MODEL)
        except DailyBudgetExhausted:
            print("Gemini: Tagesbudget der eigenen Buchführung erreicht - nicht gesendet.")
            return False

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents="Antworte nur mit dem Wort: bereit",
            )
        except errors.ServerError as error:
            code = getattr(error, "code", "?")
            status = getattr(error, "status", "?")
            print(f"Gemini: Serverfehler bei Versuch {attempt}/{MAX_ATTEMPTS} (Code {code}, {status})")
            if attempt < MAX_ATTEMPTS:
                time.sleep(PAUSE_SECONDS)
                continue
            print("Gemini: Google antwortet dauerhaft mit Serverfehlern - später erneut versuchen.")
            return False
        except errors.APIError as error:
            code = getattr(error, "code", "?")
            status = getattr(error, "status", "?")
            print(f"Gemini: FEHLER (Code {code}, {status})")
            if code in (401, 403):
                print("  Hinweis: Schlüssel ungültig oder ohne Berechtigung (.env prüfen).")
            elif code == 404:
                print("  Hinweis: Modellbezeichnung unbekannt (GEMINI_MODEL in der .env prüfen).")
            elif code == 429:
                print("  Hinweis: Anfragelimit erreicht - nicht wiederholen, sondern warten.")
            return False
        except Exception as error:
            print(f"Gemini: FEHLER bei der Anfrage ({type(error).__name__})")
            return False

        answer = (response.text or "").strip()
        print(f"Gemini: OK (google-genai {package_version('google-genai')}, Antwort: {answer})")
        return True

    return False


if __name__ == "__main__":
    mcp_ok = check_mcp_import()
    gemini_ok = check_gemini_access()

    if mcp_ok and gemini_ok:
        print("\nAlles bereit.")
    else:
        print("\nBitte die Fehler oben beheben, bevor wir weitermachen.")
        sys.exit(1)