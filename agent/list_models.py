import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import errors

# Listet die Modelle auf, die zu einem Suchbegriff passen, mit ihrer technischen
# Kennung und den unterstützten Aktionen. Die Kennung (der Teil nach "models/")
# ist das, was im Code als Modellname eingetragen wird. Der API-Schlüssel wird
# nie ausgegeben.


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY nicht gefunden (.env prüfen)")
        sys.exit(1)

    keyword = sys.argv[1].lower() if len(sys.argv) > 1 else "lite"

    client = genai.Client(api_key=api_key)

    try:
        models = list(client.models.list())
    except errors.APIError as error:
        print(
            f"Fehler beim Abrufen der Modellliste "
            f"(Code {getattr(error, 'code', '?')}, {getattr(error, 'status', '?')})"
        )
        sys.exit(1)

    found = 0
    for model in models:
        name = getattr(model, "name", "") or ""
        display = getattr(model, "display_name", "") or ""

        if keyword not in name.lower() and keyword not in display.lower():
            continue

        actions = getattr(model, "supported_actions", None) or []
        action_text = ", ".join(actions) if actions else "unbekannt"
        print(f"{name} | {display} | Aktionen: {action_text}")
        found += 1

    if found == 0:
        print(f"Keine Modelle gefunden, die '{keyword}' enthalten ({len(models)} Modelle insgesamt).")


if __name__ == "__main__":
    main()