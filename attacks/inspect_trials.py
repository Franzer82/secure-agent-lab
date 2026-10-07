import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Zeigt gespeicherte Versuche im Detail an, ohne eine Anfrage zu stellen.
# Nutzung: python3 attacks/inspect_trials.py A3 1
#   (Szenario, Anzahl der letzten gültigen Versuche, optional die Version)

# Für indirekte Angriffe: Woran erkennt man, dass das präparierte Dokument im
# Suchergebnis stand, also dem Modell überhaupt gezeigt wurde?
FIXTURE_MARKERS = {
    "A3": "helpdesk-archiv@extern.example",
    "A7": "tracker.angreifer.example",
}


def short(text, limit: int = 300) -> str:
    flat = str(text).replace("\n", " ")
    return flat if len(flat) <= limit else flat[:limit] + " ..."


def main() -> None:
    scenario_id = sys.argv[1].upper() if len(sys.argv) > 1 else "A2"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    version = sys.argv[3] if len(sys.argv) > 3 else "v1"

    path = BASE_DIR / "reports" / "raw" / f"trials_{version}.jsonl"
    if not path.exists():
        print(f"Keine Datei gefunden: {path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as file:
        trials = [json.loads(line) for line in file if line.strip()]

    selected = [t for t in trials if t["scenario_id"] == scenario_id and t["status"] != "fehler"][-limit:]
    if not selected:
        print(f"Keine gültigen Versuche für {scenario_id} gefunden.")
        sys.exit(1)

    marker = FIXTURE_MARKERS.get(scenario_id)

    for number, trial in enumerate(selected, start=1):
        print(f"=== {scenario_id}, Versuch {number}: Bewertung '{trial['status']}', Modell {trial['model']}")
        seen = False

        for run_number, run in enumerate(trial["runs"], start=1):
            notes = len(run["memory_text"].splitlines()) if run["memory_text"] else 0
            print(f"  Lauf {run_number}: {run['steps']} Schritt(e), {notes} geladene Notiz(en)")
            print(f"    Frage: {short(run['user_message'], 200)}")

            for call in run["tool_calls"]:
                state = "erlaubt" if call["allowed"] else "ABGELEHNT"
                print(f"    Tool {call['name']} {short(json.dumps(call['args'], ensure_ascii=False), 200)} [{state}]")
                print(f"      Ergebnis: {short(call['result_text'], 200)}")
                if marker and call["name"] == "search_knowledge" and marker in call["result_text"]:
                    seen = True

            print(f"    Antwort: {short(run['final_text'], 600)}")

        if marker:
            print(f"  Präpariertes Dokument stand im Suchergebnis: {'JA' if seen else 'NEIN'}")
        print()


if __name__ == "__main__":
    main()