import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lab_settings import DAILY_BUDGET, GEMINI_MODEL

# Eigene Buchführung der Anfragen pro Tag und Modell. Sie ist eine Absicherung
# VOR dem Limit, nicht die Wahrheit: Maßgeblich bleibt das Dashboard von
# AI Studio. Die Datei liegt in reports/raw/ und ist git-ignoriert.

BASE_DIR = Path(__file__).resolve().parent.parent
USAGE_FILE = BASE_DIR / "reports" / "raw" / "usage.json"

# Das Dashboard beschriftet seine Zeitachse mit UTC-8; dieselbe Tagesgrenze
# verwenden wir hier. Falls Google wegen der Sommerzeit eine Stunde früher
# zurücksetzt, ist unsere Buchführung dadurch eher vorsichtig als zu großzügig.
QUOTA_TIMEZONE = timezone(timedelta(hours=-8))


class DailyBudgetExhausted(Exception):
    """Das selbst gesetzte Tagesbudget an Anfragen ist aufgebraucht."""


def _today() -> str:
    return datetime.now(QUOTA_TIMEZONE).strftime("%Y-%m-%d")


def _load() -> dict:
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def requests_used_today(model: str) -> int:
    entry = _load().get(model, {})
    return int(entry.get("requests", 0)) if entry.get("day") == _today() else 0


def remaining_today(model: str) -> int:
    return max(0, DAILY_BUDGET - requests_used_today(model))


def record_request(model: str) -> int:
    """Zählt eine Anfrage VOR dem Senden. Es zählt JEDE Anfrage, auch
    Wiederholungen und Fehlschläge, denn auch abgelehnte Anfragen könnten auf
    das Limit angerechnet werden. Ist das Budget aufgebraucht, wird sie nicht
    gesendet."""
    used = requests_used_today(model)
    if used >= DAILY_BUDGET:
        raise DailyBudgetExhausted(f"Tagesbudget von {DAILY_BUDGET} Anfragen erreicht")

    data = _load()
    data[model] = {"day": _today(), "requests": used + 1}
    _save(data)
    return used + 1


if __name__ == "__main__":
    used = requests_used_today(GEMINI_MODEL)
    print(f"Modell:            {GEMINI_MODEL}")
    print(f"Tag (UTC-8):       {_today()}")
    print(f"Anfragen gezählt:  {used} von {DAILY_BUDGET} (Budget)")
    print(f"Noch verfügbar:    {remaining_today(GEMINI_MODEL)}")
    print("Zum Vergleich das Dashboard von AI Studio prüfen.")