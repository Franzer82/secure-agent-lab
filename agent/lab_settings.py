import os

from dotenv import load_dotenv

# Zentrale Einstellungen des Labors. Das Modell steht bewusst NICHT im Code,
# sondern in der .env: So lässt sich später ein anderes Modell prüfen, ohne
# Code anzufassen, und jede Messung hält fest, mit welchem Modell sie entstand.
#
# Das Modell wird mit seiner festen Kennung angegeben. Aliase wie "...-latest"
# werden bewusst NICHT verwendet: Sie zeigen irgendwann auf ein anderes Modell
# und würden eine Messreihe unbrauchbar machen.

load_dotenv()

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL

# Mindestabstand zwischen zwei Anfragen. Bei 15 erlaubten Anfragen pro Minute
# ergeben 5 Sekunden höchstens 12 pro Minute: Reserve statt Grenzbetrieb.
MIN_REQUEST_INTERVAL_SECONDS = _float_env("GEMINI_MIN_INTERVAL", 5.0)

# Selbst gesetztes Tagesbudget, bewusst unter dem Limit von 500 (Sicherheits-
# abstand, denn Google garantiert die Werte nicht).
DAILY_BUDGET = _int_env("GEMINI_DAILY_BUDGET", 400)